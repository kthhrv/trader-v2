import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any
import httpx
import redis.asyncio as redis
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import settings
from app.core.logger import logger


class IGClientError(Exception):
    """Base exception for IG Client."""

    pass


class IGAuthenticationError(IGClientError):
    """Raised when authentication fails."""

    pass


class AsyncIGClient:
    """
    Async client for IG Markets REST API.
    Handles multiple sessions (Demo/Live) for trading and data fetching.
    """

    _instance: Optional["AsyncIGClient"] = None

    BASE_URLS = {
        "DEMO": "https://demo-api.ig.com/gateway/deal",
        "LIVE": "https://api.ig.com/gateway/deal",
    }

    @classmethod
    def get_instance(cls) -> "AsyncIGClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.sessions: Dict[str, httpx.AsyncClient] = {}
        self.auth_tokens: Dict[str, Dict[str, str]] = {}
        self.current_account_id: Optional[str] = None
        self._lock = asyncio.Lock()
        # Shared igsession session: when IG_SHARED_SESSION_URL is set, tokens are
        # READ from that Redis instead of POSTing /session, so V2 shares the one IG
        # login held by igsession. Empty = legacy self-auth (current behaviour).
        self.session_redis: Optional[redis.Redis] = (
            redis.from_url(settings.IG_SHARED_SESSION_URL, decode_responses=True)
            if settings.IG_SHARED_SESSION_URL
            else None
        )
        self.session_env: str = settings.APP_ENV

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Closes all active httpx sessions."""
        for session in self.sessions.values():
            await session.aclose()
        self.sessions = {}

    def _normalize_env(self, env_type: str) -> str:
        """Handles fallback from LIVE to DEMO if credentials are missing."""
        if env_type == "LIVE" and not settings.IG_LIVE_API_KEY:
            return "DEMO"
        return env_type

    async def _get_session(self, env_type: str) -> httpx.AsyncClient:
        env_type = self._normalize_env(env_type)
        if env_type not in self.sessions:
            self.sessions[env_type] = httpx.AsyncClient(
                base_url=self.BASE_URLS[env_type],
                timeout=10.0,
                headers={"X-IG-API-KEY": self._get_api_key(env_type)},
            )
        return self.sessions[env_type]

    def _get_api_key(self, env_type: str) -> str:
        env_type = self._normalize_env(env_type)
        if env_type == "LIVE":
            return (
                settings.IG_LIVE_API_KEY.get_secret_value()
                if settings.IG_LIVE_API_KEY
                else ""
            )
        return settings.IG_DEMO_API_KEY.get_secret_value()

    async def _load_shared_session(
        self, env_type: str, client: httpx.AsyncClient
    ) -> None:
        """Read IG session tokens from the shared igsession Redis (env-namespaced)
        and apply them to the cache + session headers, instead of POSTing /session.
        igsession owns the one login; this NEVER authenticates."""
        key = f"ig_session:{self.session_env}:tokens"
        raw = await self.session_redis.get(key)
        if not raw:
            raise IGAuthenticationError(f"No shared IG session at {key}")
        tokens = json.loads(raw)
        cst, xst = tokens.get("cst"), tokens.get("xst")
        if not cst or not xst:
            raise IGAuthenticationError(f"Shared IG session at {key} missing cst/xst")
        self.auth_tokens[env_type] = {"CST": cst, "X-SECURITY-TOKEN": xst}
        client.headers.update({"CST": cst, "X-SECURITY-TOKEN": xst})
        creds = (
            settings._get_live_credentials()
            if env_type == "LIVE"
            else settings._get_demo_credentials()
        )
        self.current_account_id = creds["acc_id"]
        logger.info(
            f"Loaded shared IG session ({env_type}) from {key}. "
            f"Account: {self.current_account_id}"
        )

    async def authenticate(self, env_type: str = "DEMO"):
        """
        Authenticates against the specified IG environment.
        Sets X-SECURITY-TOKEN and CST headers for subsequent requests.
        """
        env_type = self._normalize_env(env_type)

        async with self._lock:
            if env_type in self.auth_tokens:
                return

            client = await self._get_session(env_type)
            # Clear old tokens if any to ensure a clean login request
            client.headers.pop("CST", None)
            client.headers.pop("X-SECURITY-TOKEN", None)

            # Shared session: read igsession's tokens, never POST /session.
            if self.session_redis is not None:
                await self._load_shared_session(env_type, client)
                return

            creds = (
                settings._get_live_credentials()
                if env_type == "LIVE"
                else settings._get_demo_credentials()
            )

            payload = {
                "identifier": creds["username"],
                "password": creds["password"].get_secret_value(),
            }

            headers = {
                "VERSION": "2",
                "X-IG-API-KEY": creds["api_key"].get_secret_value(),
            }

            try:
                logger.info(
                    f"Authenticating AsyncIGClient with {env_type} environment..."
                )
                response = await client.post("/session", json=payload, headers=headers)
                response.raise_for_status()

                cst = response.headers.get("CST")
                x_security_token = response.headers.get("X-SECURITY-TOKEN")

                if not cst or not x_security_token:
                    raise IGAuthenticationError(
                        "Missing auth tokens in response headers"
                    )

                self.auth_tokens[env_type] = {
                    "CST": cst,
                    "X-SECURITY-TOKEN": x_security_token,
                }

                client.headers.update(
                    {"CST": cst, "X-SECURITY-TOKEN": x_security_token}
                )

                account_info = response.json()
                self.current_account_id = account_info.get("currentAccountId")
                logger.info(
                    f"Successfully authenticated {env_type}. Account: {self.current_account_id}"
                )

            except httpx.HTTPStatusError as e:
                logger.error(f"IG Auth Failed ({env_type}): {e.response.text}")
                raise IGAuthenticationError(
                    f"HTTP {e.response.status_code}: {e.response.text}"
                )
            except Exception as e:
                logger.error(f"IG Auth Error ({env_type}): {e}")
                raise IGAuthenticationError(str(e))

    async def _api_request(
        self, method: str, endpoint: str, env_type: str = "LIVE", **kwargs
    ) -> httpx.Response:
        """
        Internal helper to make API requests with auto-reauthentication on 401.
        """
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)

        try:
            response = await client.request(method, endpoint, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            # Check for 401 or specific IG token errors
            # IG sometimes returns 401 for expired tokens, sometimes 403 with specific error codes
            is_token_error = (
                e.response.status_code == 401
                or "error.security.client-token-missing" in e.response.text
                or "error.security.client-token-invalid" in e.response.text
            )

            if is_token_error:
                logger.warning(
                    f"Token expired/missing for {env_type}. Re-authenticating..."
                )

                # Invalidate local token
                if env_type in self.auth_tokens:
                    del self.auth_tokens[env_type]

                # Clear session headers to prevent them being sent during re-auth or retry
                client.headers.pop("CST", None)
                client.headers.pop("X-SECURITY-TOKEN", None)

                # Re-authenticate
                # Note: authenticate() has a lock, so it handles concurrency
                await self.authenticate(env_type)

                # Retry the request once
                # Note: 'authenticate' updates the session headers, so 'client' is already fresh
                logger.info(f"Retrying request to {endpoint} after re-auth")
                response = await client.request(method, endpoint, **kwargs)
                response.raise_for_status()
                return response
            else:
                # Re-raise other HTTP errors
                raise e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def fetch_historical_prices(
        self,
        epic: str,
        resolution: str,
        num_points: int,
        env_type: str = settings.DATA_ACCOUNT_ENV,
    ) -> Dict[str, Any]:
        url = f"prices/{epic}/{resolution}/{num_points}"
        headers = {"VERSION": "2"}
        try:
            response = await self._api_request(
                "GET", url, env_type=env_type, headers=headers
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch prices for {epic}: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}: {e.response.text}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def fetch_historical_prices_by_range(
        self,
        epic: str,
        resolution: str,
        start_date: str,
        end_date: str,
        env_type: str = settings.DATA_ACCOUNT_ENV,
    ) -> Dict[str, Any]:
        url = f"prices/{epic}/{resolution}/{start_date}/{end_date}"
        headers = {"VERSION": "2"}
        try:
            response = await self._api_request(
                "GET", url, env_type=env_type, headers=headers
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch prices range for {epic}: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}: {e.response.text}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def fetch_market_details(
        self, epic: str, env_type: str = settings.DATA_ACCOUNT_ENV
    ) -> Dict[str, Any]:
        """
        Fetches full market details including snapshot (Bid/Offer).
        """
        url = f"markets/{epic}"
        headers = {"VERSION": "3"}
        try:
            response = await self._api_request(
                "GET", url, env_type=env_type, headers=headers
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Failed to fetch market details for {epic}: {e.response.text}"
            )
            raise IGClientError(f"HTTP {e.response.status_code}: {e.response.text}")

    async def get_account_balance(
        self, env_type: str = settings.TRADING_ACCOUNT_ENV
    ) -> float:
        headers = {"VERSION": "1"}
        try:
            response = await self._api_request(
                "GET", "/accounts", env_type=env_type, headers=headers
            )
            accounts = response.json().get("accounts", [])
            if not accounts:
                return 0.0

            target_account = None
            if self.current_account_id:
                for acc in accounts:
                    if acc.get("accountId") == self.current_account_id:
                        target_account = acc
                        break

            if not target_account:
                logger.warning(
                    f"Current account {self.current_account_id} not found in list. Using first account."
                )
                target_account = accounts[0]

            # The 'balance' field in the account object is itself a dictionary
            # containing 'balance', 'deposit', 'profitLoss', and 'available'.
            balance_data = target_account.get("balance", {})
            if isinstance(balance_data, dict):
                return float(balance_data.get("balance", 0.0))
            return float(balance_data)
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch account balance: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def search_markets(
        self, search_term: str, env_type: str = settings.DATA_ACCOUNT_ENV
    ) -> Dict[str, Any]:
        url = f"markets?searchTerm={search_term}"
        headers = {"VERSION": "1"}
        try:
            response = await self._api_request(
                "GET", url, env_type=env_type, headers=headers
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Search failed: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def fetch_market_by_epic(
        self, epic: str, env_type: str = settings.DATA_ACCOUNT_ENV
    ) -> Dict[str, Any]:
        """
        Fetches basic market details by epic (lighter than fetch_market_details).
        Useful for getting marketId.
        """
        headers = {"VERSION": "3"}
        url = f"markets/{epic}"
        try:
            response = await self._api_request(
                "GET", url, env_type=env_type, headers=headers
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch market {epic}: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def fetch_client_sentiment_by_instrument(
        self, market_id: str, env_type: str = settings.DATA_ACCOUNT_ENV
    ) -> Dict[str, Any]:
        """
        Fetches client sentiment (long/short %) for a given market ID.
        """
        headers = {"VERSION": "1"}
        url = f"clientsentiment/{market_id}"
        try:
            response = await self._api_request(
                "GET", url, env_type=env_type, headers=headers
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"Failed to fetch sentiment for {market_id}: {e.response.text}"
            )
            return {}  # Return empty dict on failure (non-critical)

    async def update_open_position(
        self,
        deal_id: str,
        stop_level: float,
        limit_level: Optional[float] = None,
        env_type: str = settings.TRADING_ACCOUNT_ENV,
    ):
        headers = {"VERSION": "2", "_method": "PUT"}
        payload = {"stopLevel": stop_level, "limitLevel": limit_level}
        try:
            response = await self._api_request(
                "PUT",
                f"/positions/otc/{deal_id}",
                json=payload,
                headers=headers,
                env_type=env_type,
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to update position {deal_id}: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def fetch_open_positions(
        self, env_type: str = settings.TRADING_ACCOUNT_ENV
    ) -> Dict[str, Any]:
        headers = {"VERSION": "2"}
        try:
            response = await self._api_request(
                "GET", "/positions", headers=headers, env_type=env_type
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch open positions: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def fetch_transaction_history(
        self,
        max_span_seconds: int = 172800,
        env_type: str = settings.TRADING_ACCOUNT_ENV,
    ) -> Dict[str, Any]:
        # API expects milliseconds
        period_millis = max_span_seconds * 1000

        # Using V1 endpoint (V2 often problematic for history?)
        headers = {"VERSION": "1"}
        url = f"/history/transactions/ALL_DEAL/{period_millis}"
        try:
            response = await self._api_request(
                "GET", url, headers=headers, env_type=env_type
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch history: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def fetch_activity_history(
        self,
        max_span_seconds: int = 86400,
        deal_id: Optional[str] = None,
        env_type: str = settings.TRADING_ACCOUNT_ENV,
    ) -> Dict[str, Any]:
        """
        Fetches activity history. Uses Version 3.
        Supports filtering by deal_id directly.
        """
        url = "history/activity"

        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=max_span_seconds)
        from_str = start.strftime("%Y-%m-%dT%H:%M:%S")
        to_str = now.strftime("%Y-%m-%dT%H:%M:%S")

        params: Dict[str, Any] = {"detailed": "true", "from": from_str, "to": to_str}

        if deal_id:
            # Note: IG API V3 docs say dealId filter is supported
            params["dealId"] = deal_id

        headers = {"VERSION": "3"}
        try:
            response = await self._api_request(
                "GET", url, headers=headers, params=params, env_type=env_type
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch activity history: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def close_open_position(
        self,
        deal_id: str,
        direction: str,
        size: float,
        env_type: str = settings.TRADING_ACCOUNT_ENV,
    ) -> Dict[str, Any]:
        """
        Closes an open position.
        Direction should be the OPPOSITE of the opening direction.
        """
        headers = {"VERSION": "1", "_method": "DELETE"}
        payload = {
            "dealId": deal_id,
            "direction": direction,
            "size": size,
            "orderType": "MARKET",
        }
        try:
            # IG uses DELETE for closing OTC positions
            # Note: We use POST with _method=DELETE if the client doesn't support DELETE with body,
            # but httpx handles DELETE with body fine. However, IG often expects POST to /positions/otc
            # with _method=DELETE header.
            # The original code used client.post("/positions/otc", ...)
            response = await self._api_request(
                "POST",
                "/positions/otc",
                json=payload,
                headers=headers,
                env_type=env_type,
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to close position {deal_id}: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def fetch_deal_confirmation(
        self, deal_reference: str, env_type: str = settings.TRADING_ACCOUNT_ENV
    ) -> Dict[str, Any]:
        """
        Fetches the confirmation for a deal reference to get the actual Deal ID.
        """
        headers = {"VERSION": "1"}
        url = f"/confirms/{deal_reference}"
        try:
            response = await self._api_request(
                "GET", url, headers=headers, env_type=env_type
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Failed to fetch confirmation for {deal_reference}: {e.response.text}"
            )
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def create_order(
        self,
        epic: str,
        direction: str,
        size: float,
        stop_level: float,
        limit_level: Optional[float] = None,
        env_type: str = settings.TRADING_ACCOUNT_ENV,
    ) -> Dict[str, Any]:
        payload = {
            "epic": epic,
            "direction": direction,
            "size": size,
            "stopLevel": stop_level,
            "limitLevel": limit_level,
            "orderType": "MARKET",
            "guaranteedStop": False,
            "forceOpen": True,
            "currencyCode": "GBP",
            "expiry": "DFB",
        }
        headers = {"VERSION": "2"}
        try:
            response = await self._api_request(
                "POST",
                "/positions/otc",
                json=payload,
                headers=headers,
                env_type=env_type,
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Order placement failed: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}: {e.response.text}")

import asyncio
from typing import Dict, Optional, Any
import httpx
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

    BASE_URLS = {
        "DEMO": "https://demo-api.ig.com/gateway/deal",
        "LIVE": "https://api.ig.com/gateway/deal",
    }

    def __init__(self):
        self.sessions: Dict[str, httpx.AsyncClient] = {}
        self.auth_tokens: Dict[str, Dict[str, str]] = {}
        self._lock = asyncio.Lock()

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
                logger.info(
                    f"Successfully authenticated {env_type}. Account: {account_info.get('currentAccountId')}"
                )

            except httpx.HTTPStatusError as e:
                logger.error(f"IG Auth Failed ({env_type}): {e.response.text}")
                raise IGAuthenticationError(
                    f"HTTP {e.response.status_code}: {e.response.text}"
                )
            except Exception as e:
                logger.error(f"IG Auth Error ({env_type}): {e}")
                raise IGAuthenticationError(str(e))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def fetch_historical_prices(
        self, epic: str, resolution: str, num_points: int, env_type: str = "LIVE"
    ) -> Dict[str, Any]:
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        url = f"prices/{epic}/{resolution}/{num_points}"
        headers = {"VERSION": "2"}

        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
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
        env_type: str = "LIVE",
    ) -> Dict[str, Any]:
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        url = f"prices/{epic}/{resolution}/{start_date}/{end_date}"
        headers = {"VERSION": "2"}

        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
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
        self, epic: str, env_type: str = "LIVE"
    ) -> Dict[str, Any]:
        """
        Fetches full market details including snapshot (Bid/Offer).
        """
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        url = f"markets/{epic}"
        headers = {"VERSION": "3"}

        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Failed to fetch market details for {epic}: {e.response.text}"
            )
            raise IGClientError(f"HTTP {e.response.status_code}: {e.response.text}")

    async def get_account_balance(self, env_type: str = "DEMO") -> float:
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        headers = {"VERSION": "1"}

        try:
            response = await client.get("/accounts", headers=headers)
            response.raise_for_status()
            accounts = response.json().get("accounts", [])
            if not accounts:
                return 0.0

            # The 'balance' field in the account object is itself a dictionary
            # containing 'balance', 'deposit', 'profitLoss', and 'available'.
            balance_data = accounts[0].get("balance", {})
            if isinstance(balance_data, dict):
                return float(balance_data.get("balance", 0.0))
            return float(balance_data)
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch account balance: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def search_markets(
        self, search_term: str, env_type: str = "LIVE"
    ) -> Dict[str, Any]:
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        url = f"markets?searchTerm={search_term}"
        headers = {"VERSION": "1"}

        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Search failed: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def update_open_position(
        self,
        deal_id: str,
        stop_level: float,
        limit_level: Optional[float] = None,
        env_type: str = "LIVE",
    ):
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        headers = {"VERSION": "2", "_method": "PUT"}
        payload = {"stopLevel": stop_level, "limitLevel": limit_level}

        try:
            response = await client.put(
                f"/positions/otc/{deal_id}", json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to update position {deal_id}: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def fetch_open_positions(self, env_type: str = "LIVE") -> Dict[str, Any]:
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        headers = {"VERSION": "2"}

        try:
            response = await client.get("/positions", headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch open positions: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def fetch_transaction_history(
        self, max_span_seconds: int = 172800, env_type: str = "LIVE"
    ) -> Dict[str, Any]:
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        # API expects milliseconds
        period_millis = max_span_seconds * 1000

        # Using V1 endpoint (V2 often problematic for history?)
        headers = {"VERSION": "1"}
        url = f"/history/transactions/ALL_DEAL/{period_millis}"

        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch history: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def fetch_deal_confirmation(
        self, deal_reference: str, env_type: str = "LIVE"
    ) -> Dict[str, Any]:
        """
        Fetches the confirmation for a deal reference to get the actual Deal ID.
        """
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        headers = {"VERSION": "1"}
        url = f"/confirms/{deal_reference}"

        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
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
        env_type: str = "DEMO",
    ) -> Dict[str, Any]:
        env_type = self._normalize_env(env_type)
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
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
            response = await client.post(
                "/positions/otc", json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Order placement failed: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}: {e.response.text}")

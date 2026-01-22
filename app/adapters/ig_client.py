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

    async def _get_session(self, env_type: str) -> httpx.AsyncClient:
        if env_type not in self.sessions:
            self.sessions[env_type] = httpx.AsyncClient(
                base_url=self.BASE_URLS[env_type],
                timeout=10.0,
                headers={"X-IG-API-KEY": self._get_api_key(env_type)},
            )
        return self.sessions[env_type]

    def _get_api_key(self, env_type: str) -> str:
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
        async with self._lock:
            if env_type in self.auth_tokens:
                # Check if token is still valid (simplified for now)
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

                # IG returns tokens in headers
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

                # Update session headers for future calls
                client.headers.update(
                    {"CST": cst, "X-SECURITY-TOKEN": x_security_token}
                )

                # Fetch account ID if not explicitly set (optional check)
                account_info = response.json()
                logger.info(
                    f"Successfully authenticated {env_type}. Account: {account_info.get('accountId')}"
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
        """
        Fetches historical prices for a given epic.
        Defaults to LIVE environment for better data quotas.
        """
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)

        # IG Resolution mapping if needed, but usually matches (e.g., MIN, MIN_5, etc.)
        # For now assuming resolution is passed correctly per IG API
        url = f"/prices/{epic}/{resolution}/{num_points}"
        headers = {"VERSION": "3"}

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
        """
        Fetches historical prices for a given range.
        Dates should be in format: 'YYYY-MM-DDT00:00:00'
        """
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)

        # URL format for date range: /prices/{epic}/{resolution}/{startDate}/{endDate}
        url = f"/prices/{epic}/{resolution}/{start_date}/{end_date}"
        headers = {"VERSION": "3"}

        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch prices range for {epic}: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}: {e.response.text}")

    async def update_open_position(
        self,
        deal_id: str,
        stop_level: float,
        limit_level: Optional[float] = None,
        env_type: str = "LIVE",
    ):
        """
        Updates the Stop/Limit levels of an open position.
        """
        if env_type not in self.auth_tokens:
            await self.authenticate(env_type)

        client = await self._get_session(env_type)
        headers = {
            "VERSION": "2",
            "_method": "PUT",
        }  # Method override often required for PUT in IG

        payload = {"stopLevel": stop_level, "limitLevel": limit_level}

        try:
            # Endpoint: /positions/otc/{dealId}
            response = await client.put(
                f"/positions/otc/{deal_id}", json=payload, headers=headers
            )
            response.raise_for_status()
            logger.info(f"Updated position {deal_id}: Stop={stop_level}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to update position {deal_id}: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}")

    async def create_order(
        self,
        epic: str,
        direction: str,
        size: float,
        stop_level: float,
        limit_level: Optional[float] = None,
        env_type: str = "DEMO",  # Trading usually defaults to DEMO in dev
    ) -> Dict[str, Any]:
        """
        Places a market order (Spread Bet / CFD).
        """
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

        headers = {"VERSION": "2"}  # v2 is common for orders

        try:
            response = await client.post(
                "/positions/otc", json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Order placement failed: {e.response.text}")
            raise IGClientError(f"HTTP {e.response.status_code}: {e.response.text}")

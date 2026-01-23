from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Project Paths ---
    ROOT_DIR: Path = Path(__file__).parent.parent.parent
    LOGS_DIR: Path = ROOT_DIR / "logs"
    DATA_DIR: Path = ROOT_DIR / "data"
    DB_PATH: Path = DATA_DIR / "trader.db"

    # --- IG Markets: Demo Credentials ---
    IG_DEMO_API_KEY: SecretStr = Field(alias="IG_DEMO_API_KEY")
    IG_DEMO_USERNAME: str = Field(alias="IG_DEMO_USERNAME")
    IG_DEMO_PASSWORD: SecretStr = Field(alias="IG_DEMO_PASSWORD")
    IG_DEMO_ACC_ID: str = Field(alias="IG_DEMO_ACC_ID")

    # --- IG Markets: Live Credentials ---
    # Optional to allow starting up without Live keys initially
    IG_LIVE_API_KEY: Optional[SecretStr] = Field(default=None, alias="IG_LIVE_API_KEY")
    IG_LIVE_USERNAME: Optional[str] = Field(default=None, alias="IG_LIVE_USERNAME")
    IG_LIVE_PASSWORD: Optional[SecretStr] = Field(
        default=None, alias="IG_LIVE_PASSWORD"
    )
    IG_LIVE_ACC_ID: Optional[str] = Field(default=None, alias="IG_LIVE_ACC_ID")

    # --- Account Selection ---
    # Select which account is used for Executing Trades
    TRADING_ACCOUNT_ENV: Literal["DEMO", "LIVE"] = "DEMO"

    # Select which account is used for Fetching Market Data (Live often has better limits)
    DATA_ACCOUNT_ENV: Literal["DEMO", "LIVE"] = "LIVE"

    # --- Risk Management ---
    RISK_PER_TRADE_PERCENT: float = 0.01
    CONSECUTIVE_LOSS_LIMIT: int = 4
    MIN_ACCOUNT_BALANCE: float = 0.0
    BREAKEVEN_TRIGGER_R: float = 1.5

    # --- External Services ---
    GEMINI_API_KEY: SecretStr

    HA_API_URL: str = "http://192.168.0.207:8123"
    HA_ACCESS_TOKEN: Optional[SecretStr] = None
    HA_NOTIFY_ENTITY: str = "notify.mobile_app_pixel_8"

    # --- Build Info ---
    GIT_COMMIT_SHA: str = Field(default="unknown", alias="GIT_COMMIT_SHA")

    @property
    def trading_credentials(self) -> dict:
        """Returns the credential set configured for TRADING."""
        if self.TRADING_ACCOUNT_ENV == "LIVE":
            return self._get_live_credentials()
        return self._get_demo_credentials()

    @property
    def data_credentials(self) -> dict:
        """Returns the credential set configured for DATA FETCHING."""
        if self.DATA_ACCOUNT_ENV == "LIVE":
            # Fallback to Demo if Live is requested but not configured
            if not self.IG_LIVE_API_KEY:
                return self._get_demo_credentials()
            return self._get_live_credentials()
        return self._get_demo_credentials()

    def _get_demo_credentials(self) -> dict:
        return {
            "api_key": self.IG_DEMO_API_KEY,
            "username": self.IG_DEMO_USERNAME,
            "password": self.IG_DEMO_PASSWORD,
            "acc_id": self.IG_DEMO_ACC_ID,
            "type": "DEMO",
        }

    def _get_live_credentials(self) -> dict:
        return {
            "api_key": self.IG_LIVE_API_KEY,
            "username": self.IG_LIVE_USERNAME,
            "password": self.IG_LIVE_PASSWORD,
            "acc_id": self.IG_LIVE_ACC_ID,
            "type": "LIVE",
        }


settings = Settings()  # type: ignore

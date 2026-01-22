from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class VolatilityRegime(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TrendContext(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class MarketRegime(BaseModel):
    """
    Encapsulates the technical state of the market.
    """

    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    timestamp: datetime

    # Prices
    current_price: float
    daily_open: float
    prev_close: float

    # Volatility
    atr_14: float
    avg_atr: float
    volatility_ratio: float
    regime: VolatilityRegime

    # Trend
    ema_20: float
    trend: TrendContext
    rsi_14: float

    # Session
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    gap_percent: float

    @property
    def is_high_volatility(self) -> bool:
        return self.regime == VolatilityRegime.HIGH


class StrategyContext(BaseModel):
    """
    The full context passed to the AI Analyst.
    """

    market: MarketRegime
    news_summary: str
    active_position: Optional[dict] = None  # Placeholder for position info

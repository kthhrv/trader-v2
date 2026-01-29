from enum import Enum
from datetime import datetime
from typing import Optional, Any, List
from pydantic import BaseModel, ConfigDict


class VolatilityRegime(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TrendContext(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class MarketIndicators(BaseModel):
    """Raw technical values."""

    atr_14: float
    avg_atr: float
    rsi_14: float
    adx_14: Optional[float] = None
    ema_20: float
    rvol: float = 1.0  # Relative Volume
    ema_slope: float = 0.0
    extension_factor: float = 0.0  # (Price - EMA) / ATR


class MarketState(BaseModel):
    """Interpreted market state."""

    trend: TrendContext
    volatility: VolatilityRegime
    volatility_ratio: float
    is_parabolic: bool = False
    is_choppy: bool = False


class MarketRegime(BaseModel):
    """
    Encapsulates the technical state of the market.
    """

    model_config = ConfigDict(use_enum_values=True, extra="allow")

    symbol: str
    timestamp: datetime

    # Prices
    current_price: float
    daily_open: float
    prev_close: float
    gap_percent: float
    session_high: Optional[float] = None
    session_low: Optional[float] = None

    # Nested Components
    indicators: MarketIndicators
    state: MarketState

    # External Factors
    vix_level: Optional[float] = None
    client_sentiment: Optional[dict] = None  # e.g. {'long': 60, 'short': 40}

    # Extra Context Data (Dynamically attached)
    candles_5m: Optional[List[Any]] = None
    candles_1m: Optional[List[Any]] = None
    candles_daily: Optional[List[Any]] = None
    trend_table: Optional[str] = None

    # Backward Compatibility Properties (Accessors)
    @property
    def rsi_14(self) -> float:
        return self.indicators.rsi_14

    @property
    def adx_14(self) -> Optional[float]:
        return self.indicators.adx_14

    @property
    def atr_14(self) -> float:
        return self.indicators.atr_14

    @property
    def avg_atr(self) -> float:
        return self.indicators.avg_atr

    @property
    def ema_20(self) -> float:
        return self.indicators.ema_20

    @property
    def regime(self) -> VolatilityRegime:
        return self.state.volatility

    @property
    def volatility_ratio(self) -> float:
        return self.state.volatility_ratio

    @property
    def trend(self) -> TrendContext:
        return self.state.trend


class StrategyContext(BaseModel):
    """
    The full context passed to the AI Analyst.
    """

    market: MarketRegime
    news_summary: str
    active_position: Optional[dict] = None

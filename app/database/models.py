from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class TradeLog(SQLModel, table=True):
    """
    Records the lifecycle of a trade execution.
    """

    __tablename__ = "trade_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Trade Details
    symbol: str = Field(index=True)
    direction: str  # BUY or SELL
    action: str  # OPEN, CLOSE, MODIFY

    # Price Data
    price: float
    size: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # Outcome
    pnl: Optional[float] = None
    fees: Optional[float] = None

    # Metadata
    strategy_name: str
    deal_id: Optional[str] = Field(default=None, index=True)
    signal_id: Optional[str] = None  # Link to Gemini analysis
    notes: Optional[str] = None


class HistoricalCandle(SQLModel, table=True):
    """
    Stores OHLCV data for analysis and backtesting.
    """

    __tablename__ = "historical_candles"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    resolution: str  # 1Min, 5Min, 15Min, 1H, 1D
    timestamp: datetime = Field(index=True)

    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None

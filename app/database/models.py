from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, DateTime


class TradeSignal(SQLModel, table=True):
    """
    The AI-generated trading plan.
    """

    __tablename__ = "trade_signals"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Context
    symbol: str = Field(index=True)
    strategy_name: str

    # Analysis
    signal_decision: str  # BUY, SELL, WAIT
    confidence: str
    reasoning: str

    # Plan Parameters
    entry_price: float
    entry_type: str = "BREAKOUT"  # Default to BREAKOUT
    stop_loss: float
    take_profit: Optional[float] = None
    position_size: float

    # Risk Context
    atr_at_generation: float

    # Relationship
    execution: Optional["TradeExecution"] = Relationship(back_populates="signal")


class TradeExecution(SQLModel, table=True):
    """
    The actual broker execution details.
    """

    __tablename__ = "trade_executions"

    id: Optional[int] = Field(default=None, primary_key=True)
    signal_id: Optional[int] = Field(default=None, foreign_key="trade_signals.id")

    # Broker Info
    deal_id: str = Field(index=True)
    direction: str  # BUY / SELL

    # Execution Details
    fill_price: float
    fill_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    size: float

    # Management
    initial_stop_loss: float
    current_stop_loss: float  # Updated by trailing stop

    # Outcome
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    pnl: Optional[float] = None
    outcome_status: str = "OPEN"  # OPEN, WIN, LOSS, BREAKEVEN

    # Relationships
    signal: Optional[TradeSignal] = Relationship(back_populates="execution")
    post_mortem: Optional["TradePostMortem"] = Relationship(back_populates="execution")


class TradePostMortem(SQLModel, table=True):
    """
    After-action review of a closed trade.
    """

    __tablename__ = "trade_post_mortems"

    id: Optional[int] = Field(default=None, primary_key=True)
    execution_id: int = Field(foreign_key="trade_executions.id")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    did_follow_plan: bool
    stop_loss_critique: str
    slippage_impact: str
    reasoning_quality: str
    key_lesson: str
    verdict: str

    # Relationship
    execution: Optional[TradeExecution] = Relationship(back_populates="post_mortem")


class HistoricalCandle(SQLModel, table=True):
    """
    Stores OHLCV data for analysis and backtesting.
    """

    __tablename__ = "historical_candles"

    symbol: str = Field(primary_key=True, index=True)
    resolution: str = Field(primary_key=True)  # MINUTE, MINUTE_5, MINUTE_15, HOUR
    timestamp: datetime = Field(
        sa_column=Column(DateTime(timezone=True), primary_key=True),
    )

    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None

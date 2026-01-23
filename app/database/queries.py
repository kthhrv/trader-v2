from typing import List, Tuple
from datetime import datetime
from sqlmodel import select, desc, asc
from app.database.session import async_session_maker
from app.database.models import TradeSignal, TradeExecution, HistoricalCandle


async def get_trade_candles(
    symbol: str, start_time: datetime, end_time: datetime
) -> List[HistoricalCandle]:
    """
    Fetches 1-minute candles for a specific trade window.
    """
    async with async_session_maker() as session:
        statement = (
            select(HistoricalCandle)
            .where(HistoricalCandle.symbol == symbol)
            .where(HistoricalCandle.timestamp >= start_time)
            .where(HistoricalCandle.timestamp <= end_time)
            .order_by(asc(HistoricalCandle.timestamp))
        )
        results = await session.execute(statement)
        return results.scalars().all()


async def get_recent_trades_joined(
    limit: int = 5,
) -> List[Tuple[TradeExecution, TradeSignal]]:
    """
    Fetches recent trade executions joined with their signals.
    """
    async with async_session_maker() as session:
        statement = (
            select(TradeExecution, TradeSignal)
            .join(
                TradeSignal,
                onclause=TradeExecution.signal_id == TradeSignal.id,  # type: ignore
                isouter=True,
            )
            .order_by(desc(TradeExecution.fill_time))
            .limit(limit)
        )
        results = await session.execute(statement)
        return results.all()


async def get_all_trades() -> List[Tuple[TradeExecution, TradeSignal]]:
    """
    Fetches ALL trade executions joined with their signals for analytics.
    """
    async with async_session_maker() as session:
        statement = (
            select(TradeExecution, TradeSignal)
            .join(
                TradeSignal,
                onclause=TradeExecution.signal_id == TradeSignal.id,  # type: ignore
                isouter=True,
            )
            .order_by(desc(TradeExecution.fill_time))
        )
        results = await session.execute(statement)
        return results.all()


async def get_all_signals() -> List[TradeSignal]:
    """
    Fetches all trade signals for funnel analysis.
    """
    async with async_session_maker() as session:
        statement = select(TradeSignal)
        results = await session.execute(statement)
        return results.scalars().all()

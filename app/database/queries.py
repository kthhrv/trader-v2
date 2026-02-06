from typing import List, Tuple, Optional, Any, cast
from datetime import datetime
from sqlmodel import select, desc, asc, delete
from app.database.session import async_session_maker
from app.database.models import (
    TradeSignal,
    TradeExecution,
    HistoricalCandle,
    TradePostMortem,
    TradeActorState,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.trade_actor import TradeActor


async def save_trade_actor_state(session: AsyncSession, actor: TradeActor):
    """
    Persists the current state and history of a TradeActor.
    """
    db_state = await session.get(TradeActorState, actor.trade_id)
    if not db_state:
        db_state = TradeActorState(trade_id=actor.trade_id, state=actor.state)
        session.add(db_state)

    db_state.state = actor.state
    db_state.history = actor.history
    db_state.updated_at = datetime.now()


async def load_trade_actor_state(session: AsyncSession, trade_id: str) -> Optional[TradeActor]:
    """
    Loads a TradeActor from its persisted state.
    """
    db_state = await session.get(TradeActorState, trade_id)
    if not db_state:
        return None

    actor = TradeActor(trade_id=trade_id)
    actor.state = db_state.state
    actor.history = db_state.history
    return actor


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


async def get_recent_signals_with_executions(
    limit: int = 20,
) -> List[Tuple[TradeSignal, Optional[TradeExecution]]]:
    """
    Fetches recent signals joined with executions (if any).
    Useful for seeing skipped/rejected trades.
    """
    async with async_session_maker() as session:
        statement = (
            select(TradeSignal, TradeExecution)
            .join(
                TradeExecution,
                onclause=TradeSignal.id == TradeExecution.signal_id,  # type: ignore
                isouter=True,
            )
            .order_by(desc(TradeSignal.timestamp))
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


async def delete_signal_record(signal_id: int):
    """
    Deletes a TradeSignal and its associated TradeExecution and PostMortem.
    """
    async with async_session_maker() as session:
        # 1. Find the signal
        signal = await session.get(TradeSignal, signal_id)
        if not signal:
            return

        # 2. Check for executions
        statement = select(TradeExecution).where(TradeExecution.signal_id == signal_id)
        exec_results = await session.execute(statement)
        executions = exec_results.scalars().all()

        for execution in executions:
            # 3. Delete PostMortems linked to execution
            pm_stmt = delete(TradePostMortem).where(
                cast(Any, TradePostMortem.execution_id == execution.id)
            )
            await session.execute(pm_stmt)

            # 4. Delete Execution
            await session.delete(execution)

        # 5. Delete Signal
        await session.delete(signal)
        await session.commit()

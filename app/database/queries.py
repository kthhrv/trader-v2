from typing import List, Tuple
from sqlmodel import select, desc
from app.database.session import async_session_maker
from app.database.models import TradeSignal, TradeExecution


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

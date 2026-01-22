import pytest
from app.core.config import settings
from app.database.session import init_db, get_session
from app.database.models import TradeLog


@pytest.mark.asyncio
async def test_config_loads():
    assert settings.TRADING_ACCOUNT_ENV in ["DEMO", "LIVE"]
    assert settings.DATA_ACCOUNT_ENV in ["DEMO", "LIVE"]
    assert settings.DB_PATH.name == "trader.db"


@pytest.mark.asyncio
async def test_database_initialization():
    # 1. Initialize DB (creates tables)
    await init_db()

    # 2. Create a session and write a record
    async for session in get_session():
        trade = TradeLog(
            symbol="EURUSD",
            direction="BUY",
            action="OPEN",
            price=1.0500,
            size=1.0,
            strategy_name="TEST_STRAT",
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)

        assert trade.id is not None
        trade_id = trade.id

    # 3. Read it back
    async for session in get_session():
        trade = await session.get(TradeLog, trade_id)
        assert trade is not None
        assert trade.symbol == "EURUSD"

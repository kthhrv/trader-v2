import pytest
from app.core.config import settings
from app.database.session import init_db, get_session
from app.database.models import TradeSignal


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
        signal = TradeSignal(
            symbol="EURUSD",
            strategy_name="TEST",
            signal_decision="BUY",
            confidence="high",
            reasoning="test",
            entry_price=1.0,
            stop_loss=0.9,
            position_size=1.0,
            atr_at_generation=0.01,
        )
        session.add(signal)
        await session.commit()
        await session.refresh(signal)

        assert signal.id is not None
        signal_id = signal.id

    # 3. Read it back
    async for session in get_session():
        read_signal = await session.get(TradeSignal, signal_id)
        assert read_signal is not None
        assert read_signal.symbol == "EURUSD"

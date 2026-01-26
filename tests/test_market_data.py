import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock

from app.database import session as db_session
from app.database.models import HistoricalCandle
from app.database.session import init_db
from app.services.market_data import MarketDataService


@pytest.mark.asyncio
async def test_market_data_uses_cached_if_fresh():
    await init_db()

    # Seed DB with fresh data
    epic = "FRESH.EPIC"
    now = datetime.now(timezone.utc)

    async with db_session.async_session_maker() as session:
        c1 = HistoricalCandle(
            symbol=epic,
            resolution="MIN",
            timestamp=now - timedelta(seconds=30),
            open=100,
            high=100,
            low=100,
            close=100,
        )
        session.add(c1)
        await session.commit()

    # Mocks
    mock_ig = MagicMock()
    mock_collector = MagicMock()
    mock_collector.collect_market_data = AsyncMock()
    mock_collector.collect_market_data_range = AsyncMock()

    service = MarketDataService(mock_ig, mock_collector)

    # Call
    candles = await service.get_latest_candles(epic, "MIN", 1)

    # Assert
    assert len(candles) == 1
    assert candles[0].open == 100

    # Ensure fetch NOT called
    mock_collector.collect_market_data.assert_not_called()


@pytest.mark.asyncio
async def test_market_data_delta_fetch_if_stale():
    await init_db()

    # Seed DB with STALE data (2 hours old)
    epic = "STALE.EPIC"
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(hours=2)

    async with db_session.async_session_maker() as session:
        c1 = HistoricalCandle(
            symbol=epic,
            resolution="MIN",
            timestamp=stale_time,
            open=100,
            high=100,
            low=100,
            close=100,
        )
        session.add(c1)
        await session.commit()

    # Mocks
    mock_ig = MagicMock()
    mock_collector = MagicMock()
    mock_collector.collect_market_data = AsyncMock()
    mock_collector.collect_market_data_range = AsyncMock()

    service = MarketDataService(mock_ig, mock_collector)

    # Call
    # num_points = 1. Gap is 2 hours (120 mins).
    # 120 > (1 * 1.5), so it should switch to FULL fetch.
    await service.get_latest_candles(epic, "MIN", 1)

    # Assert Full Fetch Called instead of Delta
    mock_collector.collect_market_data.assert_called_once()
    mock_collector.collect_market_data_range.assert_not_called()

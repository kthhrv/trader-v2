import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone
from app.services.market_data import MarketDataService
from app.database.models import HistoricalCandle
from app.database.session import init_db, async_session_maker


@pytest.mark.asyncio
async def test_market_data_uses_cached_if_fresh():
    await init_db()

    # Seed DB with fresh data
    epic = "FRESH.EPIC"
    now = datetime.now(timezone.utc)

    async with async_session_maker() as session:
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

    service = MarketDataService(mock_ig, mock_collector)

    # Call
    candles = await service.get_latest_candles(epic, "MIN", 1)

    # Assert
    assert len(candles) == 1
    assert candles[0].symbol == epic
    # Should NOT have called collector because data is only 30s old (fresh for 1min res)
    mock_collector.collect_market_data.assert_not_called()


@pytest.mark.asyncio
async def test_market_data_fetches_if_stale():
    await init_db()

    # Seed DB with STALE data (1 hour old for 1min res)
    epic = "STALE.EPIC"
    now = datetime.now(timezone.utc)

    async with async_session_maker() as session:
        c1 = HistoricalCandle(
            symbol=epic,
            resolution="MIN",
            timestamp=now - timedelta(hours=1),
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
    # Mock collector actually doing nothing, but we verify it was CALLED
    mock_collector.collect_market_data = AsyncMock()

    service = MarketDataService(mock_ig, mock_collector)

    # Call
    await service.get_latest_candles(epic, "MIN", 1)

    # Assert
    mock_collector.collect_market_data.assert_called_once_with(epic, "MIN", 1)

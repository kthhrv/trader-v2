import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.collector import CollectorService
from app.database.models import HistoricalCandle
from app.database.session import init_db, async_session_maker
from sqlmodel import select


@pytest.mark.asyncio
async def test_collector_saves_data_to_db():
    # 1. Setup DB
    await init_db()

    # 2. Mock IG Client
    mock_ig = MagicMock()
    mock_ig.fetch_historical_prices = AsyncMock(
        return_value={
            "prices": [
                {
                    "snapshotTime": "2026/01/21 10:00:00",
                    "openPrice": {"bid": 15000, "ask": 15001},
                    "highPrice": {"bid": 15010, "ask": 15011},
                    "lowPrice": {"bid": 14990, "ask": 14991},
                    "closePrice": {"bid": 15005, "ask": 15006},
                    "lastTradedVolume": 100,
                }
            ]
        }
    )

    service = CollectorService(mock_ig)

    # 3. Run collection
    await service.collect_market_data("IX.D.NASDAQ.CASH.IP", "MIN", 1)

    # 4. Verify DB
    async with async_session_maker() as session:
        statement = select(HistoricalCandle).where(
            HistoricalCandle.symbol == "IX.D.NASDAQ.CASH.IP"
        )
        results = await session.execute(statement)
        candles = results.scalars().all()

        assert len(candles) == 1
        assert candles[0].open == 15000
        assert candles[0].resolution == "MIN"
        assert candles[0].timestamp.hour == 10


@pytest.mark.asyncio
async def test_collector_prevents_duplicates():
    await init_db()
    mock_ig = MagicMock()
    mock_ig.fetch_historical_prices = AsyncMock(
        return_value={
            "prices": [
                {
                    "snapshotTime": "2026/01/21 11:00:00",
                    "openPrice": {"bid": 100},
                    "highPrice": {"bid": 110},
                    "lowPrice": {"bid": 90},
                    "closePrice": {"bid": 105},
                }
            ]
        }
    )

    service = CollectorService(mock_ig)

    # Run twice
    await service.collect_market_data("EPIC1", "MIN", 1)
    await service.collect_market_data("EPIC1", "MIN", 1)

    async with async_session_maker() as session:
        statement = select(HistoricalCandle).where(HistoricalCandle.symbol == "EPIC1")
        results = await session.execute(statement)
        candles = results.scalars().all()

        # Should still be 1
        assert len(candles) == 1

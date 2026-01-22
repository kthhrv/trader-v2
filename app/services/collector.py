import asyncio
from datetime import datetime, timezone
from typing import List

from sqlmodel import select

from app.adapters.ig_client import AsyncIGClient
from app.database.models import HistoricalCandle
from app.database.session import async_session_maker
from app.core.markets import MARKET_CONFIGS
from app.core.config import settings
from app.core.logger import logger


class CollectorService:
    """
    Orchestrates fetching and storing historical market data.
    """

    def __init__(self, ig_client: AsyncIGClient):
        self.ig_client = ig_client

    async def collect_all_markets(self, num_points: int = 50):
        """
        Fetches data for all configured markets across multiple resolutions.
        """
        resolutions = ["MINUTE", "MINUTE_5", "MINUTE_15"]
        tasks = []

        for market_id, config in MARKET_CONFIGS.items():
            for res in resolutions:
                tasks.append(self.collect_market_data(config["epic"], res, num_points))

        await asyncio.gather(*tasks)

    async def collect_market_data(self, epic: str, resolution: str, num_points: int):
        """
        Fetches data for a specific epic/resolution and saves to DB.
        """
        try:
            logger.info(f"Collecting {num_points} {resolution} bars for {epic}...")

            raw_data = await self.ig_client.fetch_historical_prices(
                epic=epic,
                resolution=resolution,
                num_points=num_points,
                env_type=settings.DATA_ACCOUNT_ENV,
            )

            await self._process_and_save(raw_data, epic, resolution)

        except Exception as e:
            logger.error(f"Failed to collect data for {epic} ({resolution}): {e}")

    async def collect_market_data_range(
        self, epic: str, resolution: str, start_date: str, end_date: str
    ):
        """
        Fetches data for a specific time range.
        """
        try:
            logger.info(
                f"Collecting {resolution} bars for {epic} ({start_date} to {end_date})..."
            )

            raw_data = await self.ig_client.fetch_historical_prices_by_range(
                epic=epic,
                resolution=resolution,
                start_date=start_date,
                end_date=end_date,
                env_type=settings.DATA_ACCOUNT_ENV,
            )

            await self._process_and_save(raw_data, epic, resolution)

        except Exception as e:
            logger.error(f"Failed to collect data range for {epic}: {e}")

    async def _process_and_save(self, raw_data: dict, epic: str, resolution: str):
        if "prices" not in raw_data:
            logger.warning(f"No prices returned for {epic} ({resolution})")
            return

        candles = []
        for p in raw_data["prices"]:
            ts_str = p["snapshotTime"].replace("/", "-")
            if "T" not in ts_str:
                ts_str = ts_str.replace(" ", "T")

            dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)

            candle = HistoricalCandle(
                symbol=epic,
                resolution=resolution,
                timestamp=dt,
                open=p["openPrice"]["bid"],
                high=p["highPrice"]["bid"],
                low=p["lowPrice"]["bid"],
                close=p["closePrice"]["bid"],
                volume=p.get("lastTradedVolume", 0),
            )
            candles.append(candle)

        await self._save_candles(candles)
        logger.info(f"Saved {len(candles)} {resolution} bars for {epic}")

    async def _save_candles(self, candles: List[HistoricalCandle]):
        """
        Saves candles to the database, skipping duplicates.
        """
        async with async_session_maker() as session:
            for candle in candles:
                # Check for existing
                statement = select(HistoricalCandle).where(
                    HistoricalCandle.symbol == candle.symbol,
                    HistoricalCandle.resolution == candle.resolution,
                    HistoricalCandle.timestamp == candle.timestamp,
                )
                results = await session.execute(statement)
                existing = results.scalars().first()

                if not existing:
                    session.add(candle)

            await session.commit()

from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import select, desc

from app.adapters.ig_client import AsyncIGClient
from app.database.models import HistoricalCandle
from app.database.session import async_session_maker
from app.services.collector import CollectorService
from app.core.logger import logger


class MarketDataService:
    """
    Smart Data Provider: Checks DB first, fetches missing data from API.
    """

    def __init__(self, ig_client: AsyncIGClient, collector: CollectorService):
        self.ig_client = ig_client
        self.collector = collector

    async def get_latest_candles(
        self,
        epic: str,
        resolution: str,
        num_points: int,
        max_age_seconds: Optional[int] = None,
    ) -> List[HistoricalCandle]:
        """
        Retrieves the latest N candles.
        Checks DB validity first; triggers API fetch if data is missing or stale.

        Args:
            max_age_seconds: If the latest candle in DB is older than this, force an API refresh.
                             Defaults to resolution interval in seconds if None.
        """
        async with async_session_maker() as session:
            # 1. Query DB for existing candles
            statement = (
                select(HistoricalCandle)
                .where(
                    HistoricalCandle.symbol == epic,
                    HistoricalCandle.resolution == resolution,
                )
                .order_by(desc(HistoricalCandle.timestamp))
                .limit(num_points)
            )
            results = await session.execute(statement)
            candles = results.scalars().all()

            # Sort back to chronological order
            candles = sorted(candles, key=lambda c: c.timestamp)

        # 2. Check Freshness
        is_stale = False
        is_missing = len(candles) < num_points

        if not is_missing and candles:
            last_candle_time = candles[-1].timestamp
            # Ensure last_candle_time is timezone-aware (UTC)
            if last_candle_time.tzinfo is None:
                last_candle_time = last_candle_time.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)

            # Determine max age allowed
            if max_age_seconds is None:
                # Default: Stale if older than 2x resolution (heuristic)
                # Parse resolution (e.g., "MIN" -> 60s)
                interval = self._parse_resolution_to_seconds(resolution)
                max_age_seconds = interval * 2

            if (now - last_candle_time).total_seconds() > max_age_seconds:
                is_stale = True
                logger.info(
                    f"Data Stale: Last candle {last_candle_time} is > {max_age_seconds}s old."
                )

        # 3. Fetch from API if needed
        if is_missing or is_stale:
            logger.info(
                f"Fetching fresh data for {epic} (Missing: {is_missing}, Stale: {is_stale})..."
            )

            # Use collector to fetch & save
            # We fetch 'num_points' to be safe, or we could calculate delta
            await self.collector.collect_market_data(epic, resolution, num_points)

            # Re-query DB
            async with async_session_maker() as session:
                results = await session.execute(statement)
                candles = results.scalars().all()
                candles = sorted(candles, key=lambda c: c.timestamp)

        return candles

    def _parse_resolution_to_seconds(self, resolution: str) -> int:
        mapping = {
            "MIN": 60,
            "MIN_1": 60,
            "MIN_5": 300,
            "MIN_15": 900,
            "H": 3600,
            "D": 86400,
        }
        return mapping.get(resolution, 60)

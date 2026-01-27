from datetime import datetime, timezone
from sqlmodel import select

from app.adapters.ig_client import AsyncIGClient
from app.database import session as db_session
from app.database.models import HistoricalCandle
from app.core.logger import logger
from app.core.config import settings


class CollectorService:
    def __init__(self, ig_client: AsyncIGClient):
        self.ig_client = ig_client

    async def collect_market_data(self, epic: str, resolution: str, num_points: int):
        """
        Fetches latest N candles from IG and saves them.
        """
        logger.info(f"Collecting {num_points} {resolution} bars for {epic}...")
        try:
            raw_data = await self.ig_client.fetch_historical_prices(
                epic,
                resolution,
                num_points,
                env_type=settings.DATA_ACCOUNT_ENV,
            )
            await self._process_and_save(epic, resolution, raw_data)
        except Exception as e:
            logger.error(f"Failed to collect data for {epic} ({resolution}): {e}")
            raise e

    async def collect_market_data_range(
        self, epic: str, resolution: str, start_date: str, end_date: str
    ):
        """
        Fetches candles for a specific time range.
        """
        logger.info(
            f"Collecting {resolution} bars for {epic} from {start_date} to {end_date}..."
        )
        try:
            raw_data = await self.ig_client.fetch_historical_prices_by_range(
                epic,
                resolution,
                start_date,
                end_date,
                env_type=settings.DATA_ACCOUNT_ENV,
            )
            await self._process_and_save(epic, resolution, raw_data)
        except Exception as e:
            logger.error(f"Failed to collect range data for {epic}: {e}")
            raise e

    async def _process_and_save(self, epic: str, resolution: str, raw_data: dict):
        prices = raw_data.get("prices", [])
        if not prices:
            logger.warning(f"No prices returned for {epic}")
            return

        candles = []
        for p in prices:
            if not p.get("snapshotTime"):
                continue

            # Helper to safely get bid price (sometimes None or missing)
            def get_price(key):
                return (
                    float(p[key]["bid"])
                    if p.get(key) and p[key].get("bid") is not None
                    else 0.0
                )

            candle = HistoricalCandle(
                symbol=epic,
                resolution=resolution,
                timestamp=datetime.strptime(
                    p["snapshotTime"], "%Y/%m/%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc),
                open=get_price("openPrice"),
                high=get_price("highPrice"),
                low=get_price("lowPrice"),
                close=get_price("closePrice"),
                volume=float(p.get("lastTradedVolume", 0)),
            )
            candles.append(candle)

        if not candles:
            return

        # Upsert Logic (or Ignore Duplicates)
        # For simplicity/speed in SQLite, we can try insert and ignore errors,
        # or select existing timestamps.
        # Given small batches (50), checking existence is fine.

        async with db_session.async_session_maker() as session:
            # Optimize: Get all existing timestamps for this batch range
            min_ts = min(c.timestamp for c in candles)
            max_ts = max(c.timestamp for c in candles)

            stmt = select(HistoricalCandle.timestamp).where(
                HistoricalCandle.symbol == epic,
                HistoricalCandle.resolution == resolution,
                HistoricalCandle.timestamp >= min_ts,
                HistoricalCandle.timestamp <= max_ts,
            )
            result = await session.execute(stmt)
            existing = result.scalars().all()
            # Normalize DB timestamps to match incoming format (aware UTC)
            # If DB returns naive, replace with UTC.
            existing_set = {
                ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
                for ts in existing
            }

            new_candles = [c for c in candles if c.timestamp not in existing_set]

            if new_candles:
                session.add_all(new_candles)
                await session.commit()
                logger.info(f"Saved {len(new_candles)} {resolution} bars for {epic}")
            else:
                logger.info(f"No new bars to save for {epic} (all duplicates)")

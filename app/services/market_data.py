from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlmodel import select, desc

from app.adapters.ig_client import AsyncIGClient
from app.database.models import HistoricalCandle
from app.database import session as db_session
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
        Optimized to fetch only missing 'delta' if DB has recent data.
        """
        # 1. Check DB State
        async with db_session.async_session_maker() as session:
            # Get latest candle timestamp
            stmt_latest = (
                select(HistoricalCandle)
                .where(
                    HistoricalCandle.symbol == epic,
                    HistoricalCandle.resolution == resolution,
                )
                .order_by(desc(HistoricalCandle.timestamp))
                .limit(1)
            )
            latest_result = await session.execute(stmt_latest)
            latest_candle = latest_result.scalars().first()

            # Get count
            # (Simplified: just query limit N to see if we have enough)
            stmt_count = (
                select(HistoricalCandle)
                .where(
                    HistoricalCandle.symbol == epic,
                    HistoricalCandle.resolution == resolution,
                )
                .order_by(desc(HistoricalCandle.timestamp))
                .limit(num_points)
            )
            count_result = await session.execute(stmt_count)
            existing_candles = count_result.scalars().all()

        now = datetime.now(timezone.utc)
        interval_seconds = self._parse_resolution_to_seconds(resolution)
        if max_age_seconds is None:
            max_age_seconds = interval_seconds * 2

        should_fetch_full = False
        should_fetch_delta = False

        if not latest_candle:
            # Case 1: No data at all
            should_fetch_full = True
        else:
            last_time = latest_candle.timestamp.replace(tzinfo=timezone.utc)
            age = (now - last_time).total_seconds()

            if age > max_age_seconds:
                # Case 2: Data exists but is stale (gap at the end)
                should_fetch_delta = True

                # Optimize: If gap is huge (e.g. weekend gap of 3000 bars) but we only want last 100,
                # fetching the whole delta is wasteful.
                gap_bars = age / interval_seconds
                if gap_bars > (num_points * 1.5):
                    logger.info(
                        f"Gap ({int(gap_bars)} bars) > Requested ({num_points}). Switching to Full Fetch."
                    )
                    should_fetch_full = True
                    should_fetch_delta = False
                else:
                    delta_start = last_time.strftime("%Y-%m-%d %H:%M:%S")
                    # Add slight buffer to end date (IG API handles 'now' implicitly if end is future,
                    # but safer to specify or let it infer. IG Range requires both usually.)
                    # We'll use Now + 1 minute to be safe
                    delta_end = (now + timedelta(minutes=1)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

            elif len(existing_candles) < num_points:
                # Case 3: Data is fresh, but we don't have enough history (gap at the start)
                # To be safe/simple, we trigger a full fetch here to backfill.
                # Calculating exact backfill range is complex due to market hours.
                should_fetch_full = True
            else:
                logger.info(
                    f"Using cached data for {epic} ({len(existing_candles)} {resolution} bars)"
                )

        # 2. Execute Fetch
        if should_fetch_full:
            logger.info(
                f"Full fetch triggered for {epic} (Missing/Insufficient history)"
            )
            await self.collector.collect_market_data(epic, resolution, num_points)

        elif should_fetch_delta:
            logger.info(f"Delta fetch triggered for {epic} (Updating from {last_time})")
            await self.collector.collect_market_data_range(
                epic, resolution, start_date=delta_start, end_date=delta_end
            )

        # 3. Return Final Result
        async with db_session.async_session_maker() as session:
            final_stmt = (
                select(HistoricalCandle)
                .where(
                    HistoricalCandle.symbol == epic,
                    HistoricalCandle.resolution == resolution,
                )
                .order_by(desc(HistoricalCandle.timestamp))
                .limit(num_points)
            )
            results = await session.execute(final_stmt)
            candles = results.scalars().all()

        return sorted(candles, key=lambda c: c.timestamp)

    def _parse_resolution_to_seconds(self, resolution: str) -> int:
        mapping = {
            "MINUTE": 60,
            "1Min": 60,
            "MINUTE_5": 300,
            "5Min": 300,
            "MINUTE_15": 900,
            "15Min": 900,
            "HOUR": 3600,
            "1H": 3600,
            "DAY": 86400,
            "1D": 86400,
        }
        return mapping.get(resolution, 60)

    async def get_vix_level(self, vix_epic: str = "CC.D.VIX.USS.IP") -> Optional[float]:
        """
        Fetches the current VIX level (Market Fear Index).
        """
        try:
            data = await self.ig_client.fetch_market_by_epic(vix_epic)
            if data and "snapshot" in data:
                bid = data["snapshot"].get("bid")
                if bid is not None:
                    return float(bid)
        except Exception as e:
            logger.warning(f"Failed to fetch VIX: {e}")
        return None

    async def get_client_sentiment(self, epic: str) -> Optional[dict]:
        """
        Fetches client sentiment (Long/Short %) for the given epic.
        """
        try:
            # 1. Get Market ID
            market_details = await self.ig_client.fetch_market_by_epic(epic)
            if not market_details or "instrument" not in market_details:
                return None

            market_id = market_details["instrument"]["marketId"]

            # 2. Get Sentiment
            sentiment = await self.ig_client.fetch_client_sentiment_by_instrument(
                market_id
            )
            if sentiment:
                return {
                    "long": float(sentiment.get("longPositionPercentage", 0)),
                    "short": float(sentiment.get("shortPositionPercentage", 0)),
                }
        except Exception as e:
            logger.warning(f"Failed to fetch sentiment for {epic}: {e}")
        return None

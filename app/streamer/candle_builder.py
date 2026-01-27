import logging
from datetime import datetime, timezone
from typing import Dict
from app.database.session import async_session_maker
from app.database.models import HistoricalCandle

logger = logging.getLogger(__name__)


class CandleBuilder:
    """
    Aggregates ticks into 1m, 5m, and 15m candles and persists them.
    """

    def __init__(self):
        # State: {epic: { '1m': {...}, '5m': {...}, '15m': {...} } }
        self.state: Dict[str, Dict[str, dict]] = {}

    async def on_tick(self, epic: str, bid: float):
        now = datetime.now(timezone.utc)
        minute_floor = now.replace(second=0, microsecond=0)

        if epic not in self.state:
            self.state[epic] = {}

        await self._process_timeframe(epic, bid, minute_floor, "MINUTE", 1)
        await self._process_timeframe(epic, bid, minute_floor, "MINUTE_5", 5)
        await self._process_timeframe(epic, bid, minute_floor, "MINUTE_15", 15)

    async def _process_timeframe(
        self, epic: str, bid: float, now: datetime, resolution: str, interval_mins: int
    ):
        """
        Generic aggregation logic.
        interval_mins: 1, 5, 15
        """
        # Calculate the "Bucket" for this timeframe
        # E.g. for 5m, 10:03 -> 10:00. 10:06 -> 10:05.
        minute_val = now.minute
        bucket_minute = (minute_val // interval_mins) * interval_mins
        current_bucket = now.replace(minute=bucket_minute)

        state_key = resolution
        current_data = self.state[epic].get(state_key)

        # Detect New Bucket (Save Old)
        if not current_data or current_bucket > current_data["timestamp"]:
            if current_data:
                await self._save_candle(current_data, epic, resolution)

            # Init New
            self.state[epic][state_key] = {
                "timestamp": current_bucket,
                "open": bid,
                "high": bid,
                "low": bid,
                "close": bid,
                "volume": 1,
            }
        else:
            # Update Existing
            c = self.state[epic][state_key]
            if bid > c["high"]:
                c["high"] = bid
            if bid < c["low"]:
                c["low"] = bid
            c["close"] = bid
            c["volume"] += 1

    async def _save_candle(self, data: dict, epic: str, resolution: str):
        try:
            from sqlalchemy.dialects.postgresql import insert

            async with async_session_maker() as session:
                stmt = insert(HistoricalCandle).values(
                    symbol=epic,
                    resolution=resolution,
                    timestamp=data["timestamp"],
                    open=data["open"],
                    high=data["high"],
                    low=data["low"],
                    close=data["close"],
                    volume=data["volume"],
                )
                # Ignore duplicates (keep existing data)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["symbol", "resolution", "timestamp"]
                )

                await session.execute(stmt)
                await session.commit()
                logger.info(
                    f"Saved {resolution} candle for {epic} @ {data['timestamp'].strftime('%H:%M')}"
                )
        except Exception as e:
            logger.error(f"Failed to save {resolution} candle for {epic}: {e}")

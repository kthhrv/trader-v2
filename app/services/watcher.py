import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Optional
import redis.asyncio as redis

from app.core.config import settings
from app.core.logger import logger
from app.adapters.notification import HomeAssistantNotifier
from app.core.markets import MARKET_CONFIGS


class PriceSensor:
    """
    Monitors Redis market data for volatility spikes.
    """

    def __init__(self, notifier: HomeAssistantNotifier):
        self.notifier = notifier
        self.redis_client: Optional[redis.Redis] = None
        # window: {epic: deque([ (timestamp, price), ... ])}
        self.windows: Dict[str, deque] = {}
        self.window_seconds = 60
        self.threshold = 0.0015  # 0.15% spike threshold (Configurable)
        self.cooldowns: Dict[str, datetime] = {}
        self.cooldown_seconds = 300  # 5 minutes between alerts per market

    async def on_tick(self, data: dict):
        epic = data.get("epic")
        bid = data.get("bid")
        if not epic or not bid:
            return

        bid = float(bid)
        now = datetime.now(timezone.utc)

        if epic not in self.windows:
            self.windows[epic] = deque()

        # 1. Update Window
        self.windows[epic].append((now, bid))

        # 2. Cleanup Old Ticks
        while (
            self.windows[epic]
            and (now - self.windows[epic][0][0]).total_seconds() > self.window_seconds
        ):
            self.windows[epic].popleft()

        # 3. Detect Spike
        if len(self.windows[epic]) < 2:
            return

        start_price = self.windows[epic][0][1]
        pct_change = (bid - start_price) / start_price

        if abs(pct_change) >= self.threshold:
            await self._trigger_alert(epic, pct_change, bid)

    async def _trigger_alert(self, epic: str, change: float, current_price: float):
        now = datetime.now(timezone.utc)
        last_alert = self.cooldowns.get(epic)

        if last_alert and (now - last_alert).total_seconds() < self.cooldown_seconds:
            return  # Quiet during cooldown

        self.cooldowns[epic] = now

        direction = "🚀 UP" if change > 0 else "🔻 DOWN"
        market_name = next(
            (m["name"] for m in MARKET_CONFIGS.values() if m["epic"] == epic), epic
        )

        title = f"VOLATILITY ALERT: {market_name}"
        message = (
            f"{direction} {abs(change) * 100:.2f}% in < 60s. Price: {current_price}"
        )

        logger.warning(f"SPIKE DETECTED: {message}")

        # 1. Trigger Bot (Reflex) - Priority!
        if self.redis_client:
            payload = {
                "command": "RUN_STRATEGY",
                "market": next(
                    (k for k, v in MARKET_CONFIGS.items() if v["epic"] == epic), None
                ),
                "reason": f"volatility_spike_{abs(change) * 100:.2f}pct",
            }
            if payload["market"]:
                await self.redis_client.publish("trade_commands", json.dumps(payload))
                logger.info(f"Triggered Strategy for {payload['market']}")

        # 2. Send HA Notification (Background/Secondary)
        await self.notifier.send_notification(title, message, priority="high")


class WatcherService:
    """
    Orchestrates multiple sensors and manages the Redis listener loop.
    """

    def __init__(self, notifier: HomeAssistantNotifier):
        self.notifier = notifier
        self.price_sensor = PriceSensor(notifier)
        self.redis_client: Optional[redis.Redis] = None

    async def start(self):
        """
        Main loop listening to Redis.
        """
        logger.info("WatcherService starting...")
        self.redis_client = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        # Give sensor access to publisher
        self.price_sensor.redis_client = self.redis_client

        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("market_data")

        logger.info(
            f"Watcher listening to Redis 'market_data' on {settings.REDIS_HOST}"
        )

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self.price_sensor.on_tick(data)
                    except json.JSONDecodeError:
                        continue
        except asyncio.CancelledError:
            logger.info("WatcherService shutting down...")
        finally:
            await pubsub.unsubscribe("market_data")
            await self.redis_client.close()

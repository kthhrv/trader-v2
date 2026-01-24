import asyncio
import json
from typing import AsyncGenerator
import redis.asyncio as redis

from app.core.config import settings
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient


class StreamerService:
    """
    Subscribes to live market data from Redis (published by the market-streamer service).
    Yields real-time price and trade updates for a specific epic.
    """

    def __init__(self, ig_client: AsyncIGClient):
        # We keep ig_client for interface compatibility, though we use Redis for streaming
        self.ig_client = ig_client
        self.redis_host = settings.REDIS_HOST
        self.redis_port = settings.REDIS_PORT

    async def stream(self, epic: str) -> AsyncGenerator[dict, None]:
        """
        Subscribes to Redis market_data channel and yields updates for the given epic.
        """
        logger.info(f"Trader subscribing to Redis stream for {epic}...")

        r = redis.Redis(
            host=self.redis_host, port=self.redis_port, decode_responses=True
        )
        pubsub = r.pubsub()
        await pubsub.subscribe("market_data")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        # Filter by epic
                        # The market-streamer includes 'epic' or 'instrument' in the tick data
                        # Note: The JS adapter outputs 'epic' in the JSON
                        if data.get("epic") == epic:
                            yield data
                    except json.JSONDecodeError:
                        continue
        except asyncio.CancelledError:
            logger.info(f"Redis stream for {epic} cancelled.")
        finally:
            await pubsub.unsubscribe("market_data")
            await r.close()

    async def stop(self):
        """No-op for compatibility with old interface."""
        pass

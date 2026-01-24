import asyncio
import json
from typing import Set
import redis.asyncio as redis

from app.core.config import settings
from app.core.logger import logger
from app.services.trader import StrategyEngine


class CommandListener:
    """
    Listens to Redis for trading commands and executes strategies.
    Acts as the centralized execution server.
    """

    def __init__(self, engine: StrategyEngine):
        self.engine = engine
        self.redis_client: redis.Redis = None
        self.active_markets: Set[str] = set()
        self._lock = asyncio.Lock()

    async def start(self):
        """
        Main loop listening to trade_commands channel.
        """
        logger.info("CommandListener starting...")

        try:
            self.redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
            )
            pubsub = self.redis_client.pubsub()
            await pubsub.subscribe("trade_commands")

            logger.info(f"Listening for commands on {settings.REDIS_HOST}")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        payload = json.loads(message["data"])
                        await self.handle_command(payload)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON command: {message['data']}")
                        continue

        except asyncio.CancelledError:
            logger.info("CommandListener shutting down...")
        finally:
            if self.redis_client:
                await self.redis_client.close()

    async def handle_command(self, payload: dict):
        command = payload.get("command")
        market = payload.get("market")

        if command == "RUN_STRATEGY" and market:
            await self._run_strategy_safely(market, payload)
        else:
            logger.warning(f"Unknown command ignored: {payload}")

    async def _run_strategy_safely(self, market: str, payload: dict):
        async with self._lock:
            if market in self.active_markets:
                logger.warning(
                    f"Skipping command for {market}: Strategy already running."
                )
                return
            self.active_markets.add(market)

        try:
            reason = payload.get("reason", "manual")
            logger.info(f"Executing Strategy for {market} (Reason: {reason})")

            # Run the strategy (Analyst -> Execution)
            # We assume dry_run is False unless specified in payload?
            # Or use global config? For safety, let's respect global args passed to main,
            # but we can't easily access argparse here.
            # Ideally, the payload should specify execution mode.
            # For now, we default to whatever the Engine was initialized with (which comes from main.py).

            await self.engine.run_strategy(market)

        except Exception as e:
            logger.error(f"Strategy execution failed for {market}: {e}")
        finally:
            async with self._lock:
                self.active_markets.remove(market)

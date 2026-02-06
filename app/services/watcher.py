import asyncio
import json
import socket
from datetime import datetime, timezone
from typing import Dict, Optional
import redis.asyncio as redis
import pandas as pd

from app.core.config import settings
from app.core.logger import logger
from app.adapters.notification import HomeAssistantNotifier
from app.core.markets import MARKET_CONFIGS
from app.services.market_status import MarketStatusService
from app.services.technical_analysis import TechnicalAnalysisService


class MetricSensor:
    """
    Monitors 1m candles for V3 triggers (RVOL, Parabolic).
    Acts as the 'Silent Sentinel'.
    """

    def __init__(self, notifier: HomeAssistantNotifier):
        self.notifier = notifier
        self.redis_client: Optional[redis.Redis] = None
        # {epic: pd.DataFrame} - Rolling buffer of last 50 candles
        self.history: Dict[str, pd.DataFrame] = {}
        self.cooldowns: Dict[str, datetime] = {}
        self.cooldown_seconds = 300
        self.market_status = MarketStatusService()

    async def on_candle(self, data: dict):
        epic = data.get("epic")
        if not epic:
            return

        # 0. Check Market Status
        if not self.market_status.is_market_open(epic):
            return

        # 1. Update Buffer
        row = {
            "timestamp": pd.to_datetime(data["timestamp"]),
            "open": float(data["open"]),
            "high": float(data["high"]),
            "low": float(data["low"]),
            "close": float(data["close"]),
            "volume": float(data["volume"]),
        }

        if epic not in self.history:
            self.history[epic] = pd.DataFrame([row])
            self.history[epic].set_index("timestamp", inplace=True)
        else:
            new_df = pd.DataFrame([row])
            new_df.set_index("timestamp", inplace=True)
            self.history[epic] = pd.concat([self.history[epic], new_df])
            # Keep last 50
            if len(self.history[epic]) > 50:
                self.history[epic] = self.history[epic].iloc[-50:]

        df = self.history[epic]
        if len(df) < 20:  # Need enough for averages
            return

        # 2. Run Math (Silent)
        df = TechnicalAnalysisService.calculate_indicators(df)
        rvol = TechnicalAnalysisService.calculate_rvol(df)

        # 3. Check Triggers
        triggers = []

        # A. RVOL Spike
        if rvol > 2.0:
            triggers.append(f"RVOL_SPIKE_{rvol:.1f}x")

        # B. Parabolic Extension
        latest = df.iloc[-1]
        ema = latest.get("EMA_20")
        atr = latest.get("ATR")
        if ema and atr and atr > 0:
            extension = abs(latest["close"] - ema) / atr
            if extension > 2.5:
                triggers.append(f"PARABOLIC_EXT_{extension:.1f}x")

        if triggers:
            await self._trigger_bot(epic, triggers, latest["close"])

    async def _trigger_bot(self, epic: str, triggers: list, price: float):
        now = datetime.now(timezone.utc)
        last_alert = self.cooldowns.get(epic)
        if last_alert and (now - last_alert).total_seconds() < self.cooldown_seconds:
            return

        self.cooldowns[epic] = now
        reason = "+".join(triggers)
        logger.info(f"SENTINEL TRIGGER: {epic} -> {reason}")

        market_key = next(
            (k for k, v in MARKET_CONFIGS.items() if v["epic"] == epic), None
        )
        if self.redis_client and market_key:
            # Check Mode
            if settings.SENTINEL_MODE == "AUTO_TRADE":
                payload = {
                    "command": "RUN_STRATEGY",
                    "market": market_key,
                    "reason": f"sentinel_{reason}",
                }
                await self.redis_client.publish("trade_commands", json.dumps(payload))
                logger.info(f"Sentinel triggered strategy for {market_key} (AUTO_TRADE)")
            else:
                logger.info(f"Sentinel Alert Only (MONITOR_ONLY): {reason}")

            # Send HA Notification
            market_name = MARKET_CONFIGS[market_key]["name"]
            title = f"SENTINEL: {market_name}"
            if settings.SENTINEL_MODE != "AUTO_TRADE":
                title = f"[MONITOR] {title}"
                
            msg = f"Trigger: {reason} at {price}"
            await self.notifier.send_notification(title, msg, priority="high")


class WatcherService:
    """
    Orchestrates multiple sensors and manages the Redis listener loop.
    """

    def __init__(self, notifier: HomeAssistantNotifier):
        self.notifier = notifier
        self.metric_sensor = MetricSensor(notifier)
        self.redis_client: Optional[redis.Redis] = None

    async def start(self):
        """
        Main loop listening to Redis with automatic reconnection.
        """
        logger.info(f"WatcherService starting... (Mode: {settings.SENTINEL_MODE})")

        while True:
            try:
                self.redis_client = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    decode_responses=True,
                )
                self.metric_sensor.redis_client = self.redis_client

                pubsub = self.redis_client.pubsub()
                await pubsub.subscribe("market_candles")

                logger.info(
                    f"Watcher listening to 'market_candles' on {settings.REDIS_HOST}"
                )

                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            # Filter out heartbeat/start event if any
                            if data.get("event") == "candle_closed":
                                await self.metric_sensor.on_candle(data)

                        except json.JSONDecodeError:
                            continue

            except (redis.ConnectionError, socket.gaierror) as e:
                logger.warning(
                    f"Watcher lost Redis connection ({e}). Retrying in 5s..."
                )
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("WatcherService shutting down...")
                break
            except Exception as e:
                logger.exception(f"WatcherService unexpected error: {e}")
                await asyncio.sleep(5)
            finally:
                if self.redis_client:
                    try:
                        await self.redis_client.close()
                    except Exception:
                        pass

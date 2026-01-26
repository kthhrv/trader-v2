import asyncio
import socket
from datetime import datetime, timedelta, timezone
import redis.asyncio as redis
from app.core.logger import logger, configure_logging
from app.core.config import settings
from app.adapters.notification import HomeAssistantNotifier

REDIS_KEY = "health:app:last_seen"
CHECK_INTERVAL = 60  # seconds
STALE_THRESHOLD_MINUTES = 5
GRACE_PERIOD_MINUTES = 2


async def check_liveness():
    notifier = HomeAssistantNotifier()
    last_alert_sent = None
    start_time = datetime.now(timezone.utc)

    if not notifier.token:
        logger.warning(
            "Watchdog started WITHOUT notifications (HA_ACCESS_TOKEN missing). Alerts will only be logged."
        )
    else:
        logger.info(
            f"Watchdog started. Monitoring Redis key {REDIS_KEY}. Notifications enabled."
        )

    while True:
        try:
            is_stale = False
            time_diff_str = "Unknown"
            now = datetime.now(timezone.utc)
            content = None

            try:
                r = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    decode_responses=True,
                )
                content = await r.get(REDIS_KEY)
                await r.aclose()
            except (redis.RedisError, socket.gaierror) as e:
                # Infrastructure failure (Redis down or DNS issue)
                uptime_mins = (now - start_time).total_seconds() / 60
                if uptime_mins < GRACE_PERIOD_MINUTES:
                    logger.warning(
                        f"Could not connect to Redis (Still in grace period): {e}"
                    )
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue

                logger.error(f"Watchdog cannot reach Redis: {e}")
                is_stale = True
                time_diff_str = f"Redis Connection Error: {e}"

            if not is_stale:
                if content is None:
                    # Key missing
                    uptime_mins = (now - start_time).total_seconds() / 60
                    if uptime_mins < GRACE_PERIOD_MINUTES:
                        logger.info(
                            f"Heartbeat key missing, but still in grace period ({uptime_mins:.1f}/{GRACE_PERIOD_MINUTES}m). Skipping alert."
                        )
                        await asyncio.sleep(CHECK_INTERVAL)
                        continue

                    logger.warning(f"Heartbeat key {REDIS_KEY} missing!")
                    is_stale = True
                    time_diff_str = "Key Missing"
                elif isinstance(content, str):
                    # Key exists, parse it
                    try:
                        last_heartbeat = datetime.fromisoformat(content)
                        # Normalize aware datetimes
                        last_heartbeat = (
                            last_heartbeat.replace(tzinfo=timezone.utc)
                            if not last_heartbeat.tzinfo
                            else last_heartbeat
                        )
                        time_diff = now - last_heartbeat
                        is_stale = time_diff > timedelta(
                            minutes=STALE_THRESHOLD_MINUTES
                        )
                        time_diff_str = str(time_diff).split(".")[0]
                    except Exception as e:
                        logger.error(f"Error parsing heartbeat: {e}")
                        is_stale = True
                        time_diff_str = "Parse Error"

            if is_stale:
                msg = f"Trader V2 Liveness Alert: {time_diff_str}. The bot or infrastructure may be down."
                logger.error(msg)

                # Rate limit alerts to once every 30 minutes
                if last_alert_sent is None or (
                    datetime.now() - last_alert_sent
                ) > timedelta(minutes=30):
                    await notifier.send_notification(
                        title="CRITICAL: Trader V2 Liveness Alert",
                        message=msg,
                        priority="high",
                    )
                    last_alert_sent = datetime.now()
            else:
                logger.info(f"Trader V2 is alive. Last heartbeat: {time_diff_str} ago.")
                # Reset alert tracker if it becomes healthy again
                last_alert_sent = None

        except Exception as e:
            logger.error(f"Watchdog unexpected error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        configure_logging(verbose=True)
        asyncio.run(check_liveness())
    except KeyboardInterrupt:
        pass

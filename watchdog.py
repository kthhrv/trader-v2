import asyncio
from datetime import datetime, timedelta, timezone
import redis.asyncio as redis
from app.core.logger import logger
from app.core.config import settings
from app.adapters.notification import HomeAssistantNotifier

REDIS_KEY = "health:app:last_seen"
CHECK_INTERVAL = 60  # seconds
STALE_THRESHOLD_MINUTES = 5


async def check_liveness():
    notifier = HomeAssistantNotifier()
    last_alert_sent = None

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

            r = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
            )
            content = await r.get(REDIS_KEY)
            await r.close()

            if not content:
                logger.warning(f"Heartbeat key {REDIS_KEY} missing!")
                is_stale = True
                time_diff_str = "Key Missing"
            else:
                try:
                    last_heartbeat = datetime.fromisoformat(content)
                    # Use UTC if the timestamp is aware
                    now = (
                        datetime.now(timezone.utc)
                        if last_heartbeat.tzinfo
                        else datetime.now()
                    )
                    time_diff = now - last_heartbeat
                    is_stale = time_diff > timedelta(minutes=STALE_THRESHOLD_MINUTES)
                    time_diff_str = str(time_diff).split(".")[0]
                except Exception as e:
                    logger.error(f"Error parsing heartbeat: {e}")
                    is_stale = True
                    time_diff_str = "Parse Error"

            if is_stale:
                msg = f"Trader V2 bot heartbeat is stale ({time_diff_str}). The process may be hung or crashed."
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
                logger.debug(
                    f"Trader V2 is alive. Last heartbeat: {time_diff_str} ago."
                )
                # Reset alert tracker if it becomes healthy again
                last_alert_sent = None

        except Exception as e:
            logger.error(f"Watchdog error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(check_liveness())
    except KeyboardInterrupt:
        pass

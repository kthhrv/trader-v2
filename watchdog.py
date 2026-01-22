import os
import asyncio
from datetime import datetime, timedelta
from app.core.logger import logger
from app.adapters.notification import HomeAssistantNotifier

HEARTBEAT_FILE = "data/heartbeat.txt"
CHECK_INTERVAL = 60  # seconds
STALE_THRESHOLD_MINUTES = 5


async def check_liveness():
    notifier = HomeAssistantNotifier()
    last_alert_sent = None

    logger.info(f"Watchdog started. Monitoring {HEARTBEAT_FILE}")

    while True:
        try:
            is_stale = False
            time_diff_str = "Unknown"

            if not os.path.exists(HEARTBEAT_FILE):
                logger.warning(f"Heartbeat file {HEARTBEAT_FILE} missing!")
                is_stale = True
                time_diff_str = "File Missing"
            else:
                try:
                    with open(HEARTBEAT_FILE, "r") as f:
                        content = f.read().strip()
                        last_heartbeat = datetime.fromisoformat(content)
                        time_diff = datetime.now() - last_heartbeat
                        is_stale = time_diff > timedelta(
                            minutes=STALE_THRESHOLD_MINUTES
                        )
                        time_diff_str = str(time_diff).split(".")[0]
                except Exception as e:
                    logger.error(f"Error reading heartbeat file: {e}")
                    is_stale = True
                    time_diff_str = "Read Error"

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

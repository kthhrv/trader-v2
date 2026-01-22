import sys
import asyncio
from loguru import logger
from app.core.config import settings

# Remove default handler
logger.remove()

# Add File Handler (Always DEBUG)
logger.add(
    settings.LOGS_DIR / "trader-v2.log",
    rotation="10 MB",
    retention="1 week",
    level="DEBUG",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
)


def configure_logging(verbose: bool = False):
    """
    Configures the console logger level.
    Default: WARNING (Quiet)
    Verbose: INFO
    """
    level = "INFO" if verbose else "WARNING"

    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )


def enable_notification_handler():
    """
    Adds a Loguru sink that forwards ERROR/CRITICAL logs to Home Assistant.
    Uses fire-and-forget async task creation.
    """
    # Import inside function to avoid circular imports if any
    from app.adapters.notification import HomeAssistantNotifier

    notifier = HomeAssistantNotifier()
    if not notifier.token:
        logger.warning("Home Assistant token missing. Notifications disabled.")
        return

    async def _send_alert(title, msg):
        await notifier.send_notification(title, msg, priority="high")

    def ha_sink(message):
        record = message.record
        if record["level"].name in ["ERROR", "CRITICAL"]:
            title = f"TRADER V2: {record['level'].name}"
            msg = record["message"]
            # Truncate
            if len(msg) > 200:
                msg = msg[:200] + "..."

            try:
                # Fire and forget if loop exists
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(_send_alert(title, msg))
            except RuntimeError:
                # No running loop (e.g. script ending)
                pass

    logger.add(ha_sink, level="ERROR")
    logger.info("Home Assistant Notification Handler Enabled.")


def get_logger():
    return logger

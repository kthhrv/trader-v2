import sys
import asyncio
import os
from loguru import logger

# Remove default handler
logger.remove()


def configure_logging(verbose: bool = False):
    """
    Configures the console logger level.
    In Docker: Always INFO
    Local: INFO if verbose, else WARNING
    """
    # Detect Docker environment
    is_docker = os.environ.get("RUNNING_IN_DOCKER", "false").lower() == "true"

    if is_docker:
        level = "INFO"
        # Use JSON serialization for Docker/Loki
        logger.add(sys.stderr, level=level, serialize=True)
    else:
        level = "INFO" if verbose else "WARNING"
        # Use human-readable format for local dev
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

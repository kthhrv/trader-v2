import sys
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
    # Remove existing console handlers (if any) to avoid duplicates if called multiple times
    # Note: loguru doesn't easily identify handlers by sink, so we rely on this being called once
    # or we just add a new one. But since we removed all at top level, we just need to add the console one here.
    # However, this module is imported at startup.
    # To be safe, we can remove the sink `sys.stderr` if it exists, but loguru API is tricky there.
    # Simpler: The module level `logger.add` for console should be removed, and ONLY added via this function.

    # We'll rely on the top-level remove() having cleared everything, and the file handler being added.
    # We just need to add the console handler.

    level = "INFO" if verbose else "WARNING"

    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )


def get_logger():
    return logger

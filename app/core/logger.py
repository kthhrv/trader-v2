import sys
from loguru import logger
from app.core.config import settings

# Remove default handler
logger.remove()

# Add Console Handler
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)

# Add File Handler
logger.add(
    settings.LOGS_DIR / "trader-v2.log",
    rotation="10 MB",
    retention="1 week",
    level="DEBUG",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
)


def get_logger():
    return logger

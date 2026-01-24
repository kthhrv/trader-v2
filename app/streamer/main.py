import asyncio
import signal
import sys
from app.core.logger import logger, configure_logging
from app.core.config import settings
import redis.asyncio as redis
from app.streamer.manager import StreamManager

# Configure logging for the streamer service
configure_logging(verbose=True)


async def main():
    logger.info(f"Market Streamer Starting... (Build: {settings.GIT_COMMIT_SHA})")

    # 1. Connect to Redis
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        await r.ping()  # type: ignore
        logger.info(
            f"Connected to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}"
        )
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        sys.exit(1)

    # 2. Start Manager
    manager = StreamManager(r)
    await manager.start()


def handle_sigterm(*args):
    logger.info("SIGTERM received. Exiting...")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

import asyncio
import sys
import argparse
from app.core.logger import logger
from app.database.session import init_db
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService
from app.services.collector import CollectorService
from app.services.market_data import MarketDataService
from app.services.trader import StrategyEngine
from app.core.markets import MARKET_CONFIGS


async def main():
    parser = argparse.ArgumentParser(description="Trader V2")
    parser.add_argument(
        "--market",
        type=str,
        choices=list(MARKET_CONFIGS.keys()),
        help="Market key to trade",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate trades")
    parser.add_argument(
        "--init-db", action="store_true", help="Initialize database tables"
    )
    args = parser.parse_args()

    # 1. Init DB
    if args.init_db:
        logger.info("Initializing Database...")
        await init_db()
        logger.info("Database initialized.")
        if not args.market:
            return

    if not args.market:
        logger.error("Please specify --market")
        sys.exit(1)

    # 2. Setup Context
    async with AsyncIGClient() as ig_client:
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        analyst = GeminiService()

        engine = StrategyEngine(
            ig_client=ig_client,
            market_data=market_data,
            analyst=analyst,
            dry_run=args.dry_run,
        )

        # 3. Run
        try:
            await engine.run_strategy(args.market)
        except Exception as e:
            logger.exception(f"Fatal error during execution: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")

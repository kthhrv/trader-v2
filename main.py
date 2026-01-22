import asyncio
import sys
import argparse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.logger import logger
from app.database.session import init_db
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService
from app.services.collector import CollectorService
from app.services.market_data import MarketDataService
from app.services.trader import StrategyEngine
from app.core.markets import MARKET_CONFIGS


async def run_market_strategy(market_key: str, dry_run: bool):
    """Worker function for the scheduler."""
    logger.info(f"Scheduled Task: Starting {market_key} strategy...")
    async with AsyncIGClient() as ig_client:
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        analyst = GeminiService()

        engine = StrategyEngine(
            ig_client=ig_client,
            market_data=market_data,
            analyst=analyst,
            dry_run=dry_run,
        )
        await engine.run_strategy(market_key)


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
    parser.add_argument(
        "--scheduler",
        action="store_true",
        help="Start the background scheduler for all markets",
    )

    # Print help and exit if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    # 1. Init DB
    if args.init_db:
        logger.info("Initializing Database...")
        await init_db()
        logger.info("Database initialized.")
        if not args.market and not args.scheduler:
            return

    # 2. Scheduler Mode
    if args.scheduler:
        logger.info("Starting Scheduler Mode...")
        scheduler = AsyncIOScheduler()

        for market_key, config in MARKET_CONFIGS.items():
            schedule = config.get("schedule")
            timezone = config.get("timezone", "UTC")

            if schedule:
                trigger = CronTrigger(
                    day_of_week=schedule.get("day_of_week", "mon-fri"),
                    hour=schedule.get("hour"),
                    minute=schedule.get("minute"),
                    timezone=timezone,
                )
                scheduler.add_job(
                    run_market_strategy,
                    trigger,
                    args=[market_key, args.dry_run],
                    id=f"strategy_{market_key}",
                    replace_existing=True,
                )
                logger.info(
                    f"Scheduled {config['name']} ({market_key}) @ {schedule['hour']}:{schedule['minute']} {timezone}"
                )

        scheduler.start()
        logger.info("Scheduler started. Press Ctrl+C to exit.")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            pass
        return

    # 3. Single Market Run
    if not args.market:
        logger.error("Please specify --market or --scheduler")
        sys.exit(1)

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

        try:
            await engine.run_strategy(args.market)
        except Exception as e:
            logger.exception(f"Fatal error during execution: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

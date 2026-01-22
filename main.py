import asyncio
import sys
import argparse
from sqlmodel import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.logger import logger
from app.database.session import init_db, async_session_maker
from app.database.models import TradeExecution
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService
from app.adapters.news_client import NewsClient
from app.services.collector import CollectorService
from app.services.market_data import MarketDataService
from app.services.streamer import StreamerService
from app.services.trader import StrategyEngine
from app.core.markets import MARKET_CONFIGS


async def run_market_strategy(market_key: str, dry_run: bool):
    """Worker function for the scheduler."""
    logger.info(f"Scheduled Task: Starting {market_key} strategy...")
    async with AsyncIGClient() as ig_client:
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        analyst = GeminiService()
        news_client = NewsClient()
        streamer = StreamerService(ig_client)

        engine = StrategyEngine(
            ig_client=ig_client,
            market_data=market_data,
            analyst=analyst,
            news_client=news_client,
            streamer=streamer,
            dry_run=dry_run,
        )
        await engine.run_strategy(market_key)


async def run_post_mortem(deal_id: str):
    """
    Runs a post-mortem analysis for a specific deal ID.
    """
    logger.info(f"Starting Post-Mortem for Deal ID: {deal_id}")

    execution = None
    async with async_session_maker() as session:
        statement = select(TradeExecution).where(TradeExecution.deal_id == deal_id)
        results = await session.execute(statement)
        execution = results.scalars().first()

        # Eager load the signal if available.
        # Note: In pure async + lazy loading, this might need explict join or refresh
        if execution:
            await session.refresh(execution, ["signal"])

    if not execution:
        logger.error(f"Execution not found for Deal ID: {deal_id}")
        return

    logger.info(
        f"Found Trade: {execution.deal_id} ({execution.direction}) - Outcome: {execution.pnl}"
    )

    analyst = GeminiService()

    # Map to context
    trade_log_dict = {
        "deal_id": execution.deal_id,
        "entry": execution.fill_price,
        "action": execution.direction,
        "pnl": execution.pnl,
        "reasoning": execution.signal.reasoning if execution.signal else "N/A",
    }

    execution_data_dict = execution.model_dump(mode="json")

    report = await analyst.generate_post_mortem(trade_log_dict, execution_data_dict)

    if report:
        print("\n" + "=" * 60)
        print("POST-MORTEM ANALYSIS REPORT")
        print("=" * 60)
        print(f"Followed Plan: {report.did_follow_plan}")
        print(f"Stop Loss Check: {report.stop_loss_critique}")
        print(f"Slippage Impact: {report.slippage_impact}")
        print(f"Reasoning Check: {report.reasoning_quality}")
        print(f"Verdict: {report.verdict}")
        print("-" * 60)
        print(f"KEY LESSON: {report.key_lesson}")
        print("=" * 60 + "\n")
    else:
        logger.error("Failed to generate post-mortem report.")


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
        "--analyst", action="store_true", help="Generate trading plan without executing"
    )
    parser.add_argument(
        "--post-mortem", type=str, help="Run post-mortem analysis on a deal ID"
    )
    parser.add_argument(
        "--init-db", action="store_true", help="Initialize database tables"
    )
    parser.add_argument(
        "--scheduler",
        action="store_true",
        help="Start the background scheduler for all markets",
    )
    parser.add_argument("--debug-search", type=str, help="Search for markets (debug)")

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
        if not args.market and not args.scheduler and not args.post_mortem:
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

    # 3. Post Mortem
    if args.post_mortem:
        await run_post_mortem(args.post_mortem)
        return

    # 4. Debug Search
    if args.debug_search:
        async with AsyncIGClient() as ig_client:
            results = await ig_client.search_markets(
                args.debug_search, env_type="DEMO"
            )  # Force DEMO for debug
            logger.info(f"Search Results: {results}")
        return

    # 5. Single Market Run
    if not args.market:
        logger.error("Please specify --market, --scheduler, or --post-mortem")
        sys.exit(1)

    async with AsyncIGClient() as ig_client:
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        analyst = GeminiService()
        news_client = NewsClient()
        streamer = StreamerService(ig_client)

        engine = StrategyEngine(
            ig_client=ig_client,
            market_data=market_data,
            analyst=analyst,
            news_client=news_client,
            streamer=streamer,
            dry_run=args.dry_run,
            analyst_mode=args.analyst,
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

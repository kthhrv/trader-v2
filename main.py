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
from app.adapters.gemini_service import GeminiService, Action
from app.adapters.news_client import NewsClient
from app.services.collector import CollectorService
from app.services.market_data import MarketDataService
from app.services.streamer import StreamerService
from app.services.trader import StrategyEngine
from app.core.markets import MARKET_CONFIGS
from app.services.risk import RiskManager
from app.services.analyzer import MarketAnalyzer
from app.services.executor import TradeExecutor


async def run_market_strategy(market_key: str, dry_run: bool):
    """Worker function for the scheduler."""
    logger.info(f"Scheduled Task: Starting {market_key} strategy...")
    async with AsyncIGClient() as ig_client:
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        analyst = GeminiService()
        news_client = NewsClient()
        streamer = StreamerService(ig_client)

        # Instantiate Services
        risk_manager = RiskManager(ig_client)
        analyzer = MarketAnalyzer(market_data, news_client, analyst)
        executor = TradeExecutor(ig_client, streamer, dry_run)

        engine = StrategyEngine(
            analyzer=analyzer,
            risk_manager=risk_manager,
            executor=executor,
            analyst_mode=False,
        )
        # Scheduler runs fully automated logic (Generate -> Validate -> Execute)
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
        "--news", action="store_true", help="Fetch and print news for the market"
    )
    parser.add_argument(
        "--news-check",
        action="store_true",
        help="Run a health check on news fetching for all markets.",
    )
    parser.add_argument(
        "--with-rating",
        action="store_true",
        help="When using --news-check, ask Gemini to rate the relevance/quality of the news.",
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
    parser.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt for execution"
    )

    # Print help and exit if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    # 1. Init DB (Auto-heal)
    if not args.debug_search:
        await init_db()

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
            results = await ig_client.search_markets(args.debug_search, env_type="DEMO")
            logger.info(f"Search Results: {results}")
        return

    # 5. News Fetching
    if args.news:
        if not args.market:
            logger.error("Please specify --market with --news")
            return

        news_client = NewsClient()
        config = MARKET_CONFIGS.get(args.market)
        if not config:
            logger.error(f"Invalid market: {args.market}")
            return

        epic = config["epic"]
        query = "Global Financial Markets"

        if "FTSE" in epic:
            query = "FTSE 100 UK Economy"
        elif "SPX" in epic or "US500" in epic or "SPTRD" in epic:
            query = "S&P 500 US Economy"
        elif "GBP" in epic:
            query = "GBP USD Forex"
        elif "EUR" in epic:
            query = "EUR USD Forex"
        elif "DAX" in epic:
            query = "DAX 40 Germany Economy"
        elif "NIKKEI" in epic:
            query = "Nikkei 225 Japan Economy"
        elif "ASX" in epic:
            query = "ASX 200 Australia Economy"
        elif "NASDAQ" in epic:
            query = "Nasdaq 100 US Tech Sector"

        print(f"Fetching news for: {query}...")
        summary = await news_client.fetch_news(query, market=args.market)
        print(summary)
        return

    # 6. News Check
    if args.news_check:
        logger.info("Running News Health Check...")
        fetcher = NewsClient()
        analyst = GeminiService() if args.with_rating else None

        print(f"\n{'=' * 80}")
        print(f"{'NEWS HEALTH CHECK':^80}")
        if args.with_rating:
            print(f"{'(with AI Quality Audit)':^80}")
        print(f"{'=' * 80}")

        passed = 0
        failed = 0

        def get_query(epic):
            if "FTSE" in epic:
                return "FTSE 100 UK Economy"
            elif "SPX" in epic or "US500" in epic or "SPTRD" in epic:
                return "S&P 500 US Economy"
            elif "GBP" in epic:
                return "GBP USD Forex"
            elif "EUR" in epic:
                return "EUR USD Forex"
            elif "DAX" in epic or "DE30" in epic:
                return "DAX 40 Germany Economy"
            elif "NIKKEI" in epic:
                return "Nikkei 225 Japan Economy"
            elif "ASX" in epic:
                return "ASX 200 Australia Economy"
            elif "NASDAQ" in epic:
                return "Nasdaq 100 US Tech Sector"
            return "Global Financial Markets"

        targets = MARKET_CONFIGS.items()
        if args.market:
            if args.market in MARKET_CONFIGS:
                targets = [(args.market, MARKET_CONFIGS[args.market])]
            else:
                logger.error(f"Unknown market: {args.market}")
                return

        for market, config in targets:
            query = get_query(config["epic"])
            print(f"\nChecking [{market.upper()}] Query: '{query}'...")
            try:
                result = await fetcher.fetch_news(query, market=market)

                if "No recent news found" in result:
                    print("  [WARN] No news returned.")
                    failed += 1
                else:
                    lines = result.split("\n")
                    count = len([line for line in lines if line.strip()])
                    print(f"  [PASS] Retrieved content (~{count} lines).")
                    print(f"  Sample: {result[:70]}...")

                    if analyst:
                        print("  Running AI Audit...", end="", flush=True)
                        quality = await analyst.assess_news(result, market)
                        if quality:
                            print(
                                f"\r  [AI RATING] Score: {quality.score}/10 | Clarity: {quality.sentiment_clarity}"
                            )
                            print(f"  Reasoning: {quality.reasoning}")
                            if quality.score < 5:
                                print("  [WARN] Low quality news detected.")
                        else:
                            print("\r  [AI ERROR] Could not rate news.")

                    passed += 1
            except Exception as e:
                print(f"  [FAIL] Exception: {e}")
                failed += 1

        print(f"\nSummary: {passed} Passed, {failed} Failed.")
        return

    # 7. Single Market Run (Interactive)
    if not args.market:
        logger.error("Please specify --market, --scheduler, or --post-mortem")
        sys.exit(1)

    async with AsyncIGClient() as ig_client:
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        analyst = GeminiService()
        news_client = NewsClient()
        streamer = StreamerService(ig_client)

        # Instantiate Services
        risk_manager = RiskManager(ig_client)
        analyzer = MarketAnalyzer(market_data, news_client, analyst)
        executor = TradeExecutor(ig_client, streamer, args.dry_run)

        engine = StrategyEngine(
            analyzer=analyzer,
            risk_manager=risk_manager,
            executor=executor,
            analyst_mode=args.analyst,
        )

        try:
            # 1. Generate Signal
            signal, signal_db = await engine.generate_trade_signal(args.market)

            if not signal:
                logger.info("No signal generated.")
                return

            # Print Plan
            print("\n" + "=" * 50)
            print(f"TRADING PLAN: {signal.ticker}")
            print("=" * 50)
            print(f"Action: {signal.action}")
            print(f"Entry: {signal.entry}")
            print(f"Stop: {signal.stop_loss}")
            print(f"Target: {signal.take_profit}")
            print(f"Size: {signal.size}")
            print(f"Reasoning: {signal.reasoning}")
            print("-" * 50)

            if args.analyst:
                return

            if signal.action == Action.WAIT:
                logger.info("Signal is WAIT. Skipping execution.")
                return

            # 2. Confirm (if not --yes and not dry-run implicit?)
            # Usually Dry Run also asks unless --yes
            if not args.yes:
                confirm = input("\nExecute this plan? [y/N]: ").strip().lower()
                if confirm != "y":
                    logger.info("Execution cancelled by user.")
                    return

            # 3. Validate
            if not await engine.validate_signal(signal):
                logger.error("Signal failed validation (Risk/Balance). Aborting.")
                return

            # 4. Execute
            config = MARKET_CONFIGS.get(args.market)
            if config:
                await engine.execute_trade_plan(
                    signal, config["epic"], signal_db.id if signal_db else None
                )

        except Exception as e:
            logger.exception(f"Fatal error during execution: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

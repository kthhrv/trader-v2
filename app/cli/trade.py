from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService, Action
from app.adapters.news_client import NewsClient
from app.services.collector import CollectorService
from app.services.market_data import MarketDataService
from app.services.streamer import StreamerService
from app.services.trader import StrategyEngine
from app.services.risk import RiskManager
from app.services.analyzer import MarketAnalyzer
from app.services.executor import TradeExecutor
from app.core.markets import MARKET_CONFIGS


async def run_market_strategy(
    market_key: str, dry_run: bool, analyst_mode: bool = False, yes: bool = False
):
    """
    Executes the trading strategy for a specific market.
    Used by both the Scheduler and the --market CLI command.
    """
    logger.info(
        f"Starting {market_key} strategy (Dry Run: {dry_run}, Analyst: {analyst_mode})..."
    )

    config = MARKET_CONFIGS.get(market_key)
    if not config:
        logger.error(f"Invalid market key: {market_key}")
        return

    async with AsyncIGClient() as ig_client:
        # Initialize Stack
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        analyst = GeminiService()
        news_client = NewsClient()
        streamer = StreamerService(ig_client)

        risk_manager = RiskManager(ig_client)
        analyzer = MarketAnalyzer(market_data, news_client, analyst)
        executor = TradeExecutor(ig_client, streamer, dry_run)

        engine = StrategyEngine(
            analyzer=analyzer,
            risk_manager=risk_manager,
            executor=executor,
            analyst_mode=analyst_mode,
        )

        try:
            # 1. Generate Signal
            signal, signal_db = await engine.generate_trade_signal(market_key)

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

            if analyst_mode:
                return

            if signal.action == Action.WAIT:
                logger.info("Signal is WAIT. Skipping execution.")
                return

            # 2. Confirm (Interactive Only)
            # The scheduler calls this with yes=True implicitly (or we handle that logic in scheduler.py)
            # For CLI usage, yes param controls confirmation.
            if (
                not yes and not dry_run
            ):  # Dry run usually safe, but let's confirm unless forced
                # Note: In scheduler mode, 'yes' should be True.
                pass

            # If we are in interactive CLI mode (implied by not being scheduled background task), ask.
            # But here we just use the 'yes' flag.
            if not yes:
                confirm = input("\nExecute this plan? [y/N]: ").strip().lower()
                if confirm != "y":
                    logger.info("Execution cancelled by user.")
                    return

            # 3. Validate
            if not await engine.validate_signal(signal):
                logger.error("Signal failed validation (Risk/Balance). Aborting.")
                return

            # 4. Execute
            await engine.execute_trade_plan(
                signal, config["epic"], signal_db.id if signal_db else None
            )

        except Exception as e:
            logger.exception(f"Fatal error during execution: {e}")

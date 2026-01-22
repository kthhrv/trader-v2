from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService, Action, TradingSignal, EntryType
from app.adapters.news_client import NewsClient
from app.services.collector import CollectorService
from app.services.market_data import MarketDataService
from app.services.streamer import StreamerService
from app.services.trader import StrategyEngine
from app.services.risk import RiskManager
from app.services.analyzer import MarketAnalyzer
from app.services.executor import TradeExecutor
from app.services.market_status import MarketStatusService
from app.core.markets import MARKET_CONFIGS


async def run_test_trade(
    market_key: str, action: str = "BUY", dry_run: bool = False, yes: bool = False
):
    """
    Executes an immediate TEST trade with minimal size.
    Bypasses AI analysis.
    """
    logger.info(
        f"--- STARTING TEST TRADE for {market_key}, Action: {action} (Dry Run: {dry_run}) ---"
    )

    config = MARKET_CONFIGS.get(market_key)
    if not config:
        logger.error(f"Unknown market key: {market_key}")
        return

    epic = config["epic"]

    async with AsyncIGClient() as ig_client:
        try:
            # 1. Fetch Market Details for Snapshot
            market_details = await ig_client.fetch_market_details(epic)
            if not market_details or "snapshot" not in market_details:
                logger.error("Could not fetch market info for test trade.")
                return

            snapshot = market_details["snapshot"]
            current_offer = float(snapshot["offer"])
            current_bid = float(snapshot["bid"])

            # 2. Determine Entry/Stop/TP
            action_enum = Action.BUY if action.upper() == "BUY" else Action.SELL
            entry_price = 0.0
            stop_loss = 0.0
            take_profit = 0.0

            if action_enum == Action.BUY:
                entry_price = current_offer
                stop_loss = entry_price - 10.0
                take_profit = entry_price + 20.0
            else:
                entry_price = current_bid
                stop_loss = entry_price + 10.0
                take_profit = entry_price - 20.0

            # 3. Create Manual Signal
            signal = TradingSignal(
                ticker=epic,
                action=action_enum,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence="high",
                reasoning="Manual Test Trade via CLI",
                size=0.5,  # Minimal size
                atr=5.0,  # Dummy ATR
                entry_type=EntryType.INSTANT,
                use_trailing_stop=True,
            )

            # Print Plan
            print("\n" + "=" * 50)
            print(f"TEST TRADE PLAN: {market_key} ({epic})")
            print("=" * 50)
            print(f"Action: {signal.action}")
            print(f"Entry: {signal.entry}")
            print(f"Stop: {signal.stop_loss}")
            print(f"Target: {signal.take_profit}")
            print(f"Size: {signal.size}")
            print("-" * 50)

            # 4. Confirm
            if not yes and not dry_run:
                confirm = input("\nExecute this test trade? [y/N]: ").strip().lower()
                if confirm != "y":
                    logger.info("Execution cancelled by user.")
                    return

            # 5. Execute
            streamer = StreamerService(ig_client)
            executor = TradeExecutor(ig_client, streamer, dry_run)

            # Initialize Engine to save signal
            collector = CollectorService(ig_client)
            market_data = MarketDataService(ig_client, collector)
            engine = StrategyEngine(
                analyzer=MarketAnalyzer(market_data, NewsClient(), GeminiService()),
                risk_manager=RiskManager(ig_client),
                executor=executor,
                market_status=MarketStatusService(),
            )

            logger.info("Injecting Test Plan...")
            max_spread = config.get("max_spread")
            if max_spread is None:
                logger.error(
                    f"Configuration Error: 'max_spread' not defined for {market_key}. Aborting."
                )
                return

            # Save Signal for tracking
            signal_db = await engine.save_manual_signal(signal, "TEST_TRADE")

            await executor.execute_trade(signal, epic, signal_db.id, max_spread)

        except Exception as e:
            logger.exception(f"Test trade failed: {e}")


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
        market_status = MarketStatusService()

        engine = StrategyEngine(
            analyzer=analyzer,
            risk_manager=risk_manager,
            executor=executor,
            market_status=market_status,
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
            max_spread = config.get("max_spread")
            if max_spread is None:
                logger.error(
                    f"Configuration Error: 'max_spread' not defined for {market_key}. Aborting."
                )
                return

            await engine.execute_trade_plan(
                signal, config["epic"], signal_db.id if signal_db else None, max_spread
            )

        except Exception as e:
            logger.exception(f"Fatal error during execution: {e}")

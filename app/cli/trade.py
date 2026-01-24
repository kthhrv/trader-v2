import asyncio
from datetime import datetime
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import Action, TradingSignal, EntryType
from app.services.trader import StrategyResult
from app.core.markets import MARKET_CONFIGS
from app.core.container import Container


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

    async with AsyncIGClient.get_instance() as ig_client:
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
                entry_type=EntryType.BREAKOUT,
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
            engine = Container.create_strategy_engine(ig_client, dry_run=dry_run)
            executor = engine.executor

            # Start streamer explicitly if accessed manually, though executor handles it?
            # Executor takes streamer in constructor.
            # We need to access streamer to stop it.
            # engine.executor.streamer.stop() is cleaner if exposed, but executor has it private?
            # engine.executor.streamer IS available as attribute if we didn't type hint it private.
            # In Container: executor = TradeExecutor(ig_client, streamer...)
            # We need access to the streamer instance to stop it in 'finally'.
            # It's inside engine.executor.streamer.

            logger.info("Injecting Test Plan...")
            max_spread = config.get("max_spread")
            if max_spread is None:
                logger.error(
                    f"Configuration Error: 'max_spread' not defined for {market_key}. Aborting."
                )
                return

            # Save Signal for tracking
            signal_db = await engine.save_manual_signal(signal, "TEST_TRADE")

            try:
                await executor.execute_trade(signal, epic, signal_db.id, max_spread)
            finally:
                await executor.streamer.stop()

        except Exception as e:
            logger.exception(f"Test trade failed: {e}")


def confirm_trade(signal: TradingSignal) -> bool:
    """
    User confirmation callback for the StrategyEngine.
    """
    confirm = input("\nExecute this plan? [y/N]: ").strip().lower()
    return confirm == "y"


async def run_market_strategy(
    market_key: str, dry_run: bool, analyst_mode: bool = False, yes: bool = False
):
    """
    Executes the trading strategy for a specific market with stalking support.
    """
    logger.info(
        f"Starting {market_key} strategy (Dry Run: {dry_run}, Analyst: {analyst_mode}, Yes: {yes})..."
    )

    config = MARKET_CONFIGS.get(market_key)
    if not config:
        logger.error(f"Invalid market key: {market_key}")
        return

    stalk_cfg = config.get("stalking", {"enabled": False})
    duration = stalk_cfg.get("duration_minutes", 0)
    interval = stalk_cfg.get("interval_minutes", 5)
    start_time = datetime.now()

    # Determine callback based on 'yes' flag
    # If yes=True, we bypass confirmation (callback is None).
    # If yes=False, we pass the confirmation function.
    confirmation_callback = None if yes else confirm_trade

    async with AsyncIGClient.get_instance() as ig_client:
        engine = Container.create_strategy_engine(
            ig_client,
            dry_run=dry_run,
            analyst_mode=analyst_mode,
        )

        try:
            while True:
                # 1. Run Strategy
                result = await engine.run_strategy(
                    market_key, confirmation_callback=confirmation_callback
                )

                # 2. Handle Result
                if (
                    result == StrategyResult.WAIT
                    and stalk_cfg.get("enabled")
                    and not analyst_mode
                ):
                    elapsed = (datetime.now() - start_time).total_seconds() / 60
                    if elapsed < duration:
                        logger.info(
                            f"Stalking {market_key}: AI said WAIT. Sleeping {interval}m... "
                            f"(Elapsed: {elapsed:.1f}/{duration}m)"
                        )
                        await asyncio.sleep(interval * 60)
                        continue
                    else:
                        logger.info(f"Stalking {market_key}: Duration expired. Ending.")
                        break

                # For any other result (EXECUTED, SKIPPED, ERROR, HOLIDAY), or if stalking disabled
                break

        except Exception as e:
            logger.exception(f"Fatal error during execution: {e}")
        finally:
            await engine.executor.streamer.stop()

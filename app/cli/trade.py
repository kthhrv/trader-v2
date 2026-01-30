import asyncio
import uuid
from typing import Optional
from datetime import datetime
import pandas as pd
from sqlmodel import select
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import Action, TradingSignal, EntryType
from app.services.trader import StrategyResult
from app.core.markets import MARKET_CONFIGS
from app.core.container import Container
from app.database.session import async_session_maker
from app.database.models import TradeExecution, TradeSignal


async def run_sync_trade(deal_id: str):
    """
    Manually syncs a trade's outcome from IG History to the DB.
    """
    logger.info(f"Syncing trade {deal_id} from IG API...")

    async with async_session_maker() as session:
        # 1. Fetch trade from DB
        result = await session.execute(
            select(TradeExecution).where(TradeExecution.deal_id == deal_id)
        )
        trade = result.scalars().first()

        if not trade:
            logger.error(f"Trade {deal_id} not found in database.")
            return

        # Get Symbol/Epic from related signal
        epic = ""
        if trade.signal_id:
            sig_res = await session.execute(
                select(TradeSignal).where(TradeSignal.id == trade.signal_id)
            )
            signal = sig_res.scalars().first()
            epic = signal.symbol if signal else ""

        logger.info(f"Looking for closure of {epic} (Deal {deal_id})...")

        async with AsyncIGClient.get_instance() as client:
            await client.authenticate()

            # 2. Fetch History
            try:
                # Fetch last 48 hours
                history_data = await client.fetch_transaction_history(
                    max_span_seconds=172800
                )
                transactions = history_data.get("transactions", [])
            except Exception as e:
                logger.error(f"Failed to fetch history: {e}")
                return

            if not transactions:
                logger.error("No transaction history returned.")
                return

            df = pd.DataFrame(transactions)

            # 3. Find closing transaction
            date_col = "dateUtc" if "dateUtc" in df.columns else "date"
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col])
                df = df.sort_values(date_col, ascending=False)

            target_row = None

            epic_to_name_map = {
                "SPTRD": "US 500",
                "FTSE": "FTSE 100",
                "DAX": "Germany 40",
                "ASX": "Australia 200",
                "NASDAQ": "US Tech 100",
                "NIKKEI": "Japan 225",
            }

            for index, row in df.iterrows():
                pnl_str = str(row.get("profitAndLoss", ""))
                if not pnl_str or pnl_str == "nan" or pnl_str == "None":
                    continue

                try:
                    pnl_val = float(
                        pnl_str.replace("£", "").replace("A$", "").replace(",", "")
                    )
                except ValueError:
                    continue

                matched = False

                # Direct epic match
                if epic and epic in str(row.get("epic", "")):
                    matched = True

                # Name match
                if not matched:
                    inst_name = str(row.get("instrumentName", ""))
                    if epic:
                        core_code = (
                            epic.split(".")[2] if len(epic.split(".")) > 2 else ""
                        )
                        expected_name = epic_to_name_map.get(core_code, core_code)
                        if expected_name in inst_name:
                            matched = True
                    else:
                        # Fallback: check reference for deal_id
                        ref = str(row.get("reference", ""))
                        if deal_id in ref:
                            matched = True

                if matched:
                    target_row = row
                    break

            if target_row is not None:
                pnl_str = str(target_row.get("profitAndLoss", ""))
                pnl_val = float(
                    pnl_str.replace("£", "").replace("A$", "").replace(",", "")
                )
                close_level = target_row.get("closeLevel") or target_row.get("level")

                outcome = "WIN" if pnl_val > 0 else "LOSS"
                if pnl_val == 0:
                    outcome = "BREAKEVEN"

                logger.info(
                    f"Found Match! Updating Trade {deal_id}: PnL={pnl_val}, Outcome={outcome}"
                )

                trade.exit_price = float(close_level) if close_level else 0.0
                trade.pnl = pnl_val
                if date_col in target_row:
                    trade.exit_time = target_row[date_col].to_pydatetime()
                trade.outcome_status = outcome

                session.add(trade)
                await session.commit()
                logger.info("Database updated successfully.")
            else:
                logger.warning("No matching closing transaction found.")


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
    market_key: str,
    dry_run: bool,
    analyst_mode: bool = False,
    yes: bool = False,
    trigger_source: str = "manual",
    session_id: Optional[str] = None,
):
    """
    Executes the trading strategy for a specific market with stalking support.
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    logger.info(
        f"Starting {market_key} strategy (Session: {session_id}, Source: {trigger_source}, Dry Run: {dry_run}, Analyst: {analyst_mode}, Yes: {yes})..."
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
                    market_key,
                    confirmation_callback=confirmation_callback,
                    trigger_source=trigger_source,
                    session_id=session_id,
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

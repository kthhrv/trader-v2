from datetime import datetime, timezone, timedelta
import asyncio
import json
from typing import Optional
from sqlmodel import select

from app.core.config import settings
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import TradingSignal, Action
from app.services.streamer import StreamerService
from app.services.market_status import MarketStatusService
from app.database import session as db_session
from app.database.models import TradeExecution


class TradeExecutor:
    def __init__(
        self,
        ig_client: AsyncIGClient,
        streamer: StreamerService,
        market_status: MarketStatusService,
        dry_run: bool = False,
    ):
        self.ig_client = ig_client
        self.streamer = streamer
        self.market_status = market_status
        self.dry_run = dry_run

    async def execute_trade(
        self,
        signal: TradingSignal,
        epic: str,
        signal_id: Optional[int],
        max_spread: float = 5.0,
    ):
        """
        Executes trade with 'Market if Touched' logic + Trailing Stop monitoring.
        """
        if self.dry_run:
            logger.info("DRY RUN: Trade simulation successful.")
            return

        direction = "BUY" if signal.action == Action.BUY else "SELL"

        # 1. Wait for Trigger
        logger.info(
            f"Waiting for trigger: {direction} @ {signal.entry} (Max Spread: {max_spread})..."
        )
        triggered_price = await self._wait_for_trigger(
            epic, direction, signal.entry, max_spread
        )

        if not triggered_price:
            logger.warning("Trigger timeout. Trade aborted.")
            return

        logger.info(f"Triggered at {triggered_price}! Executing {direction}...")

        # 2. Place Order
        try:
            response = await self.ig_client.create_order(
                epic=epic,
                direction=direction,
                size=signal.size,
                stop_level=signal.stop_loss,
                limit_level=signal.take_profit,
                env_type=settings.TRADING_ACCOUNT_ENV,
            )
            logger.info(f"Order Placed: {response}")

            deal_id = response.get("dealId")
            if "dealReference" in response:
                deal_ref = response["dealReference"]

                # Wait for confirmation to get the real Deal ID
                logger.info(f"Waiting for confirmation of {deal_ref}...")
                for _ in range(10):  # Retry a few times
                    await asyncio.sleep(0.5)
                    try:
                        confirm = await self.ig_client.fetch_deal_confirmation(
                            deal_ref, env_type=settings.TRADING_ACCOUNT_ENV
                        )
                        if confirm.get("dealStatus") == "ACCEPTED":
                            deal_id = confirm.get("dealId")
                            logger.info(f"Order ACCEPTED. Deal ID: {deal_id}")
                            break
                        elif confirm.get("dealStatus") == "REJECTED":
                            logger.error(f"Order REJECTED: {confirm.get('reason')}")
                            return
                    except Exception:
                        pass

            if not deal_id:
                logger.error("Could not obtain Deal ID. Trade execution incomplete.")
                return

            # Save Execution
            await self._save_execution(
                signal_id=signal_id,
                deal_id=deal_id,
                direction=direction,
                fill_price=response.get("level", triggered_price),
                size=signal.size,
                stop_loss=signal.stop_loss,
            )

            # Monitor
            if signal.use_trailing_stop:
                # Need entry price for Breakeven calculation
                fill_price = float(response.get("level", triggered_price))
                await self._monitor_position(
                    deal_id,
                    epic,
                    direction,
                    fill_price,
                    signal.stop_loss,
                    signal.atr,
                    signal.size,
                )

        except Exception as e:
            logger.error(f"Execution Failed: {e}")

    async def _wait_for_trigger(
        self, epic: str, direction: str, target_entry: float, max_spread: float
    ) -> Optional[float]:
        timeout = 5400
        start_time = datetime.now(timezone.utc).timestamp()
        last_spread_warn_time = 0.0

        async for update in self.streamer.stream(epic):
            if (datetime.now(timezone.utc).timestamp() - start_time) > timeout:
                return None

            if update.get("type") == "price_update":
                bid = update.get("bid")
                offer = update.get("offer")
                if not bid or not offer:
                    continue

                # Spread Check
                current_spread = round(abs(offer - bid), 2)
                if current_spread > max_spread:
                    now = datetime.now(timezone.utc).timestamp()
                    if (now - last_spread_warn_time) > 10:
                        logger.info(
                            f"Spread {current_spread} > Max {max_spread}. Holding trigger."
                        )
                        last_spread_warn_time = now
                    continue

                if direction == "BUY":
                    if offer >= target_entry:
                        return offer
                elif direction == "SELL":
                    if bid <= target_entry:
                        return bid
        return None

    async def _monitor_position(
        self,
        deal_id: str,
        epic: str,
        direction: str,
        entry_price: float,
        current_stop: float,
        atr: float,
        size: float,
    ):
        logger.info(
            f"Starting Monitor for Deal {deal_id} (Entry: {entry_price}, Stop: {current_stop}, ATR: {atr})..."
        )

        # 0. Market Close Check Setup
        market_close_dt = None
        try:
            market_close_dt = self.market_status.get_market_close_datetime(epic)
            logger.info(f"Market Close time for {epic}: {market_close_dt}")
        except Exception as e:
            logger.warning(f"Could not determine market close time for {epic}: {e}")

        # Logic State
        moved_to_breakeven = False
        risk_distance = abs(entry_price - current_stop)

        # Configuration
        breakeven_trigger_r = settings.BREAKEVEN_TRIGGER_R

        # Trailing Parameters (Loose trail after BE)
        trail_distance = atr * 3.0
        step_size = atr * 0.1  # Min step to avoid spamming

        timeout = 28800  # 8 hours for monitoring
        start_time = datetime.now(timezone.utc).timestamp()
        last_check_time = start_time
        last_trailing_check = 0.0

        async for update in self.streamer.stream(epic):
            now_dt = datetime.now(timezone.utc)
            now = now_dt.timestamp()
            if (now - start_time) > timeout:
                logger.info("Monitor timeout.")
                break

            # 1. Handle Trade Updates (Immediate Closure Detection)
            if update.get("type") == "trade_update":
                payload_str = update.get("payload")
                if payload_str:
                    try:
                        data = json.loads(payload_str)
                        update_deal_id = data.get("dealId")
                        affected_id = data.get("affectedDealId")
                        status = data.get("status")
                        deal_status = data.get("dealStatus")

                        # Check if this update relates to our trade
                        is_match = (update_deal_id == deal_id) or (
                            affected_id == deal_id
                        )

                        if is_match:
                            # Check for closure
                            is_closed = (status in ["CLOSED", "DELETED"]) or (
                                deal_status == "ACCEPTED" and status == "CLOSED"
                            )

                            if is_closed:
                                logger.info(
                                    f"STREAM: Deal {deal_id} CLOSED via trade update."
                                )
                                await self._sync_outcome(deal_id)
                                break
                    except json.JSONDecodeError:
                        pass
                continue

            # 2. Periodic Liveness Check (Fallback)
            if (now - last_check_time) > 60:
                last_check_time = now
                if not await self._is_position_open(deal_id):
                    logger.info(f"Position {deal_id} closed. Stopping monitor.")
                    await self._sync_outcome(deal_id)
                    break

                # --- Market Close Time Check ---
                if market_close_dt:
                    # localized comparison
                    now_localized = datetime.now(market_close_dt.tzinfo)
                    time_to_close = market_close_dt - now_localized
                    # If within 15 minutes (900 seconds) of close
                    if timedelta(seconds=0) < time_to_close < timedelta(minutes=15):
                        logger.warning(
                            f"Market for {epic} closing in {time_to_close}. Forcing exit for {deal_id}."
                        )
                        try:
                            # Close Direction is opposite of opening
                            close_dir = "SELL" if direction == "BUY" else "BUY"
                            await self.ig_client.close_open_position(
                                deal_id,
                                close_dir,
                                size,
                                env_type=settings.TRADING_ACCOUNT_ENV,
                            )
                            logger.info(
                                f"Successfully force-closed {deal_id} before market close."
                            )
                            await self._sync_outcome(deal_id)
                            break
                        except Exception as e:
                            logger.error(
                                f"Failed to force-close {deal_id} near close: {e}"
                            )

            if update.get("type") == "price_update":
                bid = update.get("bid")
                offer = update.get("offer")
                if not bid or not offer:
                    continue

                # Throttle Trailing Stop Logic (Every 5s)
                if (now - last_trailing_check) < 5.0:
                    continue
                last_trailing_check = now

                current_price = bid if direction == "BUY" else offer

                # Rule 1: Check for Breakeven Trigger
                if not moved_to_breakeven and risk_distance > 0:
                    profit_dist = (
                        (current_price - entry_price)
                        if direction == "BUY"
                        else (entry_price - current_price)
                    )

                    if profit_dist >= (breakeven_trigger_r * risk_distance):
                        new_stop = entry_price

                        # Verify it's actually an improvement
                        is_better = (
                            direction == "BUY" and new_stop > current_stop
                        ) or (direction == "SELL" and new_stop < current_stop)

                        if is_better:
                            logger.info(
                                f"Moving Stop to BREAKEVEN for {deal_id} at {new_stop} (Trigger: {breakeven_trigger_r}R)"
                            )
                            if await self._update_stop_loss(deal_id, new_stop):
                                current_stop = new_stop
                                moved_to_breakeven = True

                # Rule 2: Dynamic Trailing (Only AFTER Breakeven)
                if moved_to_breakeven:
                    new_stop_candidate = None
                    if direction == "BUY":
                        target_stop = current_price - trail_distance
                        if target_stop > (current_stop + step_size):
                            new_stop_candidate = round(target_stop, 1)
                    elif direction == "SELL":
                        target_stop = current_price + trail_distance
                        if target_stop < (current_stop - step_size):
                            new_stop_candidate = round(target_stop, 1)

                    if new_stop_candidate:
                        logger.info(f"Trailing Stop Update: {new_stop_candidate}")
                        if await self._update_stop_loss(deal_id, new_stop_candidate):
                            current_stop = new_stop_candidate

    async def _update_stop_loss(self, deal_id: str, new_stop: float) -> bool:
        try:
            await self.ig_client.update_open_position(
                deal_id,
                stop_level=new_stop,
                env_type=settings.TRADING_ACCOUNT_ENV,
            )
            await self._update_execution_stop(deal_id, new_stop)
            return True
        except Exception as e:
            logger.error(f"Failed to update stop for {deal_id}: {e}")
            return False

    async def _is_position_open(self, deal_id: str) -> bool:
        """Checks if the deal is still in the open positions list."""
        try:
            data = await self.ig_client.fetch_open_positions(
                settings.TRADING_ACCOUNT_ENV
            )
            positions = data.get("positions", [])
            for p in positions:
                if p.get("position", {}).get("dealId") == deal_id:
                    return True
            return False
        except Exception as e:
            logger.warning(f"Failed to check open position status: {e}")
            return True  # Assume open on error to keep monitoring

    async def _sync_outcome(self, deal_id: str):
        """Fetches final outcome from IG history and updates DB."""

        # Retry loop to handle API lag
        for attempt in range(5):
            await asyncio.sleep(2 * (attempt + 1))  # 2s, 4s, 6s... backoff

            try:
                # Re-query DB to get context
                async with db_session.async_session_maker() as session:
                    stmt = select(TradeExecution).where(
                        TradeExecution.deal_id == deal_id
                    )
                    result = await session.execute(stmt)
                    execution = result.scalars().first()

                    if not execution:
                        logger.error(f"Execution record not found for {deal_id}")
                        return

                    # 1. Find the Closing Deal ID from Activity History (V3)
                    # The closing activity will reference our opening deal ID in 'affectedDealId'
                    activity_history = await self.ig_client.fetch_activity_history(
                        max_span_seconds=3600 * 24,
                        env_type=settings.TRADING_ACCOUNT_ENV,
                    )
                    activities = activity_history.get("activities", [])
                    closing_deal_id = None

                    for act in activities:
                        details = act.get("details", {})
                        actions = details.get("actions", [])
                        for action in actions:
                            if (
                                action.get("affectedDealId") == deal_id
                                and action.get("actionType") == "POSITION_CLOSED"
                            ):
                                closing_deal_id = act.get("dealId")
                                break
                        if closing_deal_id:
                            break

                    if not closing_deal_id:
                        logger.info(
                            f"Sync Attempt {attempt + 1}: No closing activity found for {deal_id} yet."
                        )
                        continue

                    # 2. Get PnL and Exit Price from Transaction History (V1)
                    # The transaction for the closing leg will have 'reference' == closing_deal_id
                    history = await self.ig_client.fetch_transaction_history(
                        max_span_seconds=3600 * 24,
                        env_type=settings.TRADING_ACCOUNT_ENV,
                    )
                    transactions = history.get("transactions", [])

                    for tx in transactions:
                        if tx.get("reference") == closing_deal_id:
                            # Found the closing transaction details!
                            pnl_raw = tx.get("profitAndLoss", "0")
                            try:
                                clean_pnl = float(
                                    str(pnl_raw)
                                    .replace("£", "")
                                    .replace("$", "")
                                    .replace(",", "")
                                )
                            except ValueError:
                                clean_pnl = 0.0

                            close_level = tx.get("closeLevel") or tx.get("level")
                            final_exit = float(close_level) if close_level else 0.0

                            # Update DB
                            execution.outcome_status = (
                                "WIN" if clean_pnl > 0 else "LOSS"
                            )
                            execution.pnl = clean_pnl
                            execution.exit_price = final_exit
                            execution.exit_time = datetime.now(timezone.utc)

                            session.add(execution)
                            await session.commit()
                            logger.info(
                                f"Deal {deal_id} synced via activity link {closing_deal_id}: PnL={clean_pnl}, Exit={final_exit}"
                            )
                            return  # Success

            except Exception as e:
                logger.warning(f"Sync attempt {attempt + 1} failed for {deal_id}: {e}")

        logger.error(f"Could not find matching history for {deal_id} after retries")

    async def _save_execution(
        self, signal_id, deal_id, direction, fill_price, size, stop_loss
    ):
        async with db_session.async_session_maker() as session:
            execution = TradeExecution(
                signal_id=signal_id,
                deal_id=deal_id,
                direction=direction,
                fill_price=fill_price,
                size=size,
                initial_stop_loss=stop_loss,
                current_stop_loss=stop_loss,
                outcome_status="OPEN",
            )
            session.add(execution)
            await session.commit()
            logger.info(f"Execution saved for Deal {deal_id}")

    async def _update_execution_stop(self, deal_id: str, new_stop: float):
        async with db_session.async_session_maker() as session:
            stmt = select(TradeExecution).where(TradeExecution.deal_id == deal_id)
            result = await session.execute(stmt)
            execution = result.scalars().first()
            if execution:
                execution.current_stop_loss = new_stop
                session.add(execution)
                await session.commit()

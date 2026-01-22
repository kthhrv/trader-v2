from datetime import datetime, timezone
from typing import Optional
from sqlmodel import select

from app.core.config import settings
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import TradingSignal, Action
from app.services.streamer import StreamerService
from app.database import session as db_session
from app.database.models import TradeExecution


class TradeExecutor:
    def __init__(
        self,
        ig_client: AsyncIGClient,
        streamer: StreamerService,
        dry_run: bool = False,
    ):
        self.ig_client = ig_client
        self.streamer = streamer
        self.dry_run = dry_run

    async def execute_trade(
        self, signal: TradingSignal, epic: str, signal_id: Optional[int]
    ):
        """
        Executes trade with 'Market if Touched' logic + Trailing Stop monitoring.
        """
        if self.dry_run:
            logger.info("DRY RUN: Trade simulation successful.")
            return

        direction = "BUY" if signal.action == Action.BUY else "SELL"

        # 1. Wait for Trigger
        logger.info(f"Waiting for trigger: {direction} @ {signal.entry}...")
        triggered_price = await self._wait_for_trigger(epic, direction, signal.entry)

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

            if "dealReference" in response:
                deal_ref = response["dealReference"]
                deal_id = response.get("dealId", deal_ref)

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
                    await self._monitor_position(
                        deal_id, epic, direction, signal.stop_loss, signal.atr
                    )

        except Exception as e:
            logger.error(f"Execution Failed: {e}")

    async def _wait_for_trigger(
        self, epic: str, direction: str, target_entry: float
    ) -> Optional[float]:
        timeout = 5400
        start_time = datetime.now(timezone.utc).timestamp()

        async for update in self.streamer.stream(epic):
            if (datetime.now(timezone.utc).timestamp() - start_time) > timeout:
                return None

            if update.get("type") == "price_update":
                bid = update.get("bid")
                offer = update.get("offer")
                if not bid or not offer:
                    continue

                if direction == "BUY":
                    if offer >= target_entry:
                        return offer
                elif direction == "SELL":
                    if bid <= target_entry:
                        return bid
        return None

    async def _monitor_position(
        self, deal_id: str, epic: str, direction: str, current_stop: float, atr: float
    ):
        logger.info(f"Starting Monitor for Deal {deal_id} (ATR: {atr})...")
        trail_distance = atr * 1.5
        step_size = atr * 0.5
        timeout = 7200
        start_time = datetime.now(timezone.utc).timestamp()

        async for update in self.streamer.stream(epic):
            if (datetime.now(timezone.utc).timestamp() - start_time) > timeout:
                logger.info("Monitor timeout.")
                break

            if update.get("type") == "price_update":
                bid = update.get("bid")
                offer = update.get("offer")
                if not bid or not offer:
                    continue

                new_stop = None
                if direction == "BUY":
                    market_price = bid
                    target_stop = market_price - trail_distance
                    if target_stop > (current_stop + step_size):
                        new_stop = round(target_stop, 1)
                elif direction == "SELL":
                    market_price = offer
                    target_stop = market_price + trail_distance
                    if target_stop < (current_stop - step_size):
                        new_stop = round(target_stop, 1)

                if new_stop:
                    logger.info(f"Trailing Stop Trigger: {new_stop}")
                    try:
                        await self.ig_client.update_open_position(
                            deal_id,
                            stop_level=new_stop,
                            env_type=settings.TRADING_ACCOUNT_ENV,
                        )
                        current_stop = new_stop
                        await self._update_execution_stop(deal_id, new_stop)
                    except Exception as e:
                        logger.error(f"Failed to update stop: {e}")

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

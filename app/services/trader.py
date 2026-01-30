from enum import Enum
from typing import Optional, Callable
from datetime import datetime, timedelta
from app.core.logger import logger
from app.core.markets import MARKET_CONFIGS
from app.adapters.gemini_service import TradingSignal, Action
from app.services.analyzer import MarketAnalyzer
from app.services.risk import RiskManager
from app.services.executor import TradeExecutor
from app.services.market_status import MarketStatusService
from app.database import session as db_session
from app.database.models import TradeSignal


class StrategyResult(str, Enum):
    EXECUTED = "EXECUTED"  # Trade placed or triggered
    WAIT = "WAIT"  # AI said wait
    SKIPPED = "SKIPPED"  # Risk validation failed or other skip logic
    ERROR = "ERROR"  # Unexpected error or config issue
    HOLIDAY = "HOLIDAY"  # Market closed for holiday


class StrategyEngine:
    def __init__(
        self,
        analyzer: MarketAnalyzer,
        risk_manager: RiskManager,
        executor: TradeExecutor,
        market_status: MarketStatusService,
        analyst_mode: bool = False,
    ):
        self.analyzer = analyzer
        self.risk_manager = risk_manager
        self.executor = executor
        self.market_status = market_status
        self.analyst_mode = analyst_mode

    async def run_strategy(
        self,
        market_key: str,
        confirmation_callback: Optional[Callable[[TradingSignal], bool]] = None,
        override_strategy: Optional[str] = None,
    ) -> StrategyResult:
        """
        Orchestrates the strategy flow: Analyze -> Validate -> Execute.
        """
        # 0. Check Holiday Status
        config = MARKET_CONFIGS.get(market_key)
        if config and self.market_status.is_holiday(config["epic"]):
            logger.warning(
                f"Market {market_key} is closed (Holiday). Skipping strategy."
            )
            return StrategyResult.HOLIDAY

        # 0.5 Check Market Close Proximity (No Entry Zone: 90 mins before close)
        if config:
            try:
                close_time = self.market_status.get_market_close_datetime(
                    config["epic"]
                )
                now_loc = datetime.now(close_time.tzinfo)
                time_left = close_time - now_loc

                if timedelta(seconds=0) < time_left < timedelta(minutes=90):
                    logger.warning(
                        f"Market closing soon ({time_left}). Skipping new entry (Risk: Low Liquidity/Force Close)."
                    )
                    return StrategyResult.SKIPPED
            except Exception as e:
                logger.warning(
                    f"Could not check market close time for {market_key}: {e}"
                )

        # 1. Analyze
        try:
            signal, signal_db = await self.generate_trade_signal(
                market_key, override_strategy
            )
            if not signal:
                return StrategyResult.ERROR

            if self.analyst_mode:
                logger.info(f"ANALYST REPORT: {signal.ticker} -> {signal.action}")
                return StrategyResult.EXECUTED

            if signal.action == Action.WAIT:
                return StrategyResult.WAIT

            # 2. Confirm (Delegated to callback)
            if confirmation_callback:
                if not confirmation_callback(signal):
                    logger.info("Execution cancelled by caller (callback).")
                    return StrategyResult.SKIPPED

            # 3. Validate
            if not await self.validate_signal(signal):
                logger.warning("Signal failed validation.")
                return StrategyResult.SKIPPED

            # 4. Execute
            if config:
                max_spread = config.get("max_spread")
                if max_spread is None:
                    logger.error(
                        f"Configuration Error: 'max_spread' not defined for {config.get('name')}. Aborting."
                    )
                    return StrategyResult.ERROR

                await self.execute_trade_plan(
                    signal,
                    config["epic"],
                    signal_db.id if signal_db else None,
                    max_spread,
                )
                return StrategyResult.EXECUTED

            return StrategyResult.ERROR

        except Exception as e:
            logger.error(f"Strategy execution error: {e}")
            return StrategyResult.ERROR

    async def generate_trade_signal(
        self, market_key: str, override_strategy: Optional[str] = None
    ) -> tuple[Optional[TradingSignal], Optional[TradeSignal]]:
        config = MARKET_CONFIGS.get(market_key)
        if not config:
            return None, None

        # Redundant check if called directly, but safe
        if self.market_status.is_holiday(config["epic"]):
            logger.warning(
                f"Market {market_key} is closed (Holiday). Analysis aborted."
            )
            return None, None

        logger.info(f"Generating Signal for {config['name']}...")
        signal = await self.analyzer.analyze_market(
            market_key, config, override_strategy
        )

        if not signal:
            return None, None

        logger.info(f"AI Decision: {signal.action} | Conf: {signal.confidence}")

        # Save Signal
        db_signal = await self._save_signal(
            signal, override_strategy or config.get("strategy_id", "unknown")
        )

        return signal, db_signal

    async def _save_signal(
        self, signal: TradingSignal, strategy_name: str
    ) -> TradeSignal:
        async with db_session.async_session_maker() as session:
            db_signal = TradeSignal(
                symbol=signal.ticker,
                strategy_name=strategy_name,
                signal_decision=signal.action.value,
                confidence=signal.confidence,
                reasoning=signal.reasoning,
                entry_price=signal.entry,
                entry_type=signal.entry_type.value,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                position_size=signal.size,
                atr_at_generation=signal.atr,
            )
            session.add(db_signal)
            await session.commit()
            await session.refresh(db_signal)
            return db_signal

    async def save_manual_signal(
        self, signal: TradingSignal, strategy_name: str
    ) -> TradeSignal:
        """Public wrapper for _save_signal to allow manual/test signal persistence."""
        return await self._save_signal(signal, strategy_name)

    async def validate_signal(self, signal: TradingSignal) -> bool:
        return await self.risk_manager.validate_signal(signal)

    async def execute_trade_plan(
        self,
        signal: TradingSignal,
        epic: str,
        signal_id: Optional[int],
        max_spread: float,
    ):
        await self.executor.execute_trade(signal, epic, signal_id, max_spread)

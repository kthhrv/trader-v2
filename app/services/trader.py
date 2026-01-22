import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import select

from app.core.config import settings
from app.core.logger import logger
from app.core.markets import MARKET_CONFIGS
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService, TradingSignal, Action
from app.adapters.news_client import NewsClient
from app.services.streamer import StreamerService
from app.services.market_data import MarketDataService
from app.database.session import async_session_maker
from app.database.models import TradeSignal, TradeExecution
from app.domain.models import MarketRegime, VolatilityRegime, TrendContext


class StrategyEngine:
    def __init__(
        self,
        ig_client: AsyncIGClient,
        market_data: MarketDataService,
        analyst: GeminiService,
        news_client: NewsClient,
        streamer: StreamerService,
        dry_run: bool = False,
        analyst_mode: bool = False,
    ):
        self.ig_client = ig_client
        self.market_data = market_data
        self.analyst = analyst
        self.news_client = news_client
        self.streamer = streamer
        self.dry_run = dry_run
        self.analyst_mode = analyst_mode

    async def run_strategy(self, market_key: str):
        """
        Executes the 'Market Open' strategy for a specific market.
        Orchestrates generation, validation, and execution.
        """
        # 1. Generate Signal
        signal, signal_db = await self.generate_trade_signal(market_key)

        if not signal:
            return

        if self.analyst_mode:
            logger.info(f"ANALYST REPORT:\n{signal.model_dump_json(indent=2)}")
            return

        if signal.action == Action.WAIT:
            return

        # 2. Validate Signal (Risk Check)
        if not await self.validate_signal(signal):
            logger.warning("Signal failed validation. Aborting.")
            return

        # 3. Execute
        config = MARKET_CONFIGS.get(market_key)
        if config:
            await self.execute_trade_plan(
                signal, config["epic"], signal_db.id if signal_db else None
            )

    async def generate_trade_signal(
        self, market_key: str
    ) -> tuple[Optional[TradingSignal], Optional[TradeSignal]]:
        """
        Analyzes the market and returns a Trading Signal + DB Record.
        """
        config = MARKET_CONFIGS.get(market_key)
        if not config:
            logger.error(f"Invalid market key: {market_key}")
            return None, None

        epic = config["epic"]
        logger.info(f"Generating Signal for {config['name']} ({epic})...")

        # 1. Build Market Regime (Technical Analysis)
        regime = await self._build_market_regime(epic)
        if not regime:
            logger.error("Failed to build market regime. Aborting.")
            return None, None

        # 2. Fetch News
        news_query = self._get_news_query(epic)
        logger.info(f"Fetching news for query: {news_query}")
        news_summary = await self.news_client.fetch_news(news_query, market=market_key)

        # 3. Format Context for AI
        context_str = self._format_context(regime, news_summary)

        # 4. Get AI Analysis
        signal = await self.analyst.analyze_market(context_str)

        if not signal:
            logger.error("AI returned no signal.")
            return None, None

        logger.info(f"AI Decision: {signal.action} | Conf: {signal.confidence}")

        # Save Signal to DB
        signal_db = await self._save_signal(signal, config["name"])

        return signal, signal_db

    async def validate_signal(self, signal: TradingSignal) -> bool:
        """
        Validates the signal against risk management rules.
        """
        if signal.action == Action.WAIT:
            return True

        # Fetch Account Balance
        try:
            balance = await self.ig_client.get_account_balance(
                settings.TRADING_ACCOUNT_ENV
            )
        except Exception as e:
            logger.error(f"Failed to fetch balance for validation: {e}")
            return False  # Fail safe

        # Calculate Risk Rules
        # Risk per Trade = Balance * RISK_PER_TRADE_PERCENT
        max_risk_amount = balance * settings.RISK_PER_TRADE_PERCENT

        # Floor Check: Ensure balance after potential loss remains above MIN_ACCOUNT_BALANCE
        if settings.MIN_ACCOUNT_BALANCE > 0:
            allowed_loss = balance - settings.MIN_ACCOUNT_BALANCE
            if allowed_loss <= 0:
                logger.error(
                    f"Balance ({balance}) is below Minimum Floor ({settings.MIN_ACCOUNT_BALANCE}). Trading halted."
                )
                return False
            # Cap max risk by the distance to the floor
            if max_risk_amount > allowed_loss:
                logger.warning(
                    f"Capping Risk to protect Floor: {max_risk_amount:.2f} -> {allowed_loss:.2f}"
                )
                max_risk_amount = allowed_loss

        # Trade Risk = Size * Distance        # Distance = |Entry - Stop|
        distance = abs(signal.entry - signal.stop_loss)
        if distance == 0:
            logger.error("Invalid Stop Loss: Distance is 0")
            return False

        trade_risk = signal.size * distance

        logger.info(
            f"Validation: Balance={balance:.2f}, MaxRisk={max_risk_amount:.2f}, TradeRisk={trade_risk:.2f}"
        )

        if trade_risk > max_risk_amount:
            logger.warning(
                f"Risk Violation: Trade Risk ({trade_risk:.2f}) > Max Risk ({max_risk_amount:.2f})"
            )

            # Auto-adjust size?
            # new_size = max_risk_amount / distance
            # round down to 1 decimal place? Or IG min size?
            # For safety, let's reject or clamp.

            new_size = round(max_risk_amount / distance, 2)
            if new_size < 0.5:  # Assuming min bet 0.5?
                logger.error(f"Calculated size {new_size} below minimum. rejecting.")
                return False

            logger.info(f"Adjusting Size: {signal.size} -> {new_size}")
            signal.size = new_size  # Mutate signal

        return True

    async def execute_trade_plan(
        self, signal: TradingSignal, epic: str, signal_id: Optional[int]
    ):
        """
        Executes the trade via IG Client.
        Waits for price trigger if entry type is INSTANT (Market if Touched).
        """
        if self.dry_run:
            logger.info("DRY RUN: Trade simulation successful.")
            return

        direction = "BUY" if signal.action == Action.BUY else "SELL"

        # 1. Wait for Entry Trigger
        logger.info(f"Waiting for trigger: {direction} @ {signal.entry}...")
        triggered_price = await self._wait_for_trigger(epic, direction, signal.entry)

        if not triggered_price:
            logger.warning("Trigger timeout or cancellation. Trade aborted.")
            return

        logger.info(f"Triggered at {triggered_price}! Executing {direction}...")

        try:
            # 2. Place Order
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

                await self._save_execution(
                    signal_id=signal_id,
                    deal_id=deal_id,
                    direction=direction,
                    fill_price=response.get("level", triggered_price),
                    size=signal.size,
                    stop_loss=signal.stop_loss,
                )

                if signal.use_trailing_stop:
                    await self._monitor_position(
                        deal_id, epic, direction, signal.stop_loss, signal.atr
                    )

        except Exception as e:
            logger.error(f"Execution Failed: {e}")

    def _get_news_query(self, epic: str) -> str:
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
        else:
            return "Global Financial Markets"

    async def _build_market_regime(self, epic: str) -> Optional[MarketRegime]:
        """
        Fetches data and calculates indicators to form the Market Regime.
        """
        # Fetch 15m data for indicators (50 points)
        candles_15m = await self.market_data.get_latest_candles(epic, "MINUTE_15", 50)

        # Fetch 5m data for granular structure (24 points = 2 hours)
        candles_5m = await self.market_data.get_latest_candles(epic, "MINUTE_5", 24)

        # Fetch 1m data for precise timing (15 points = 15 mins)
        candles_1m = await self.market_data.get_latest_candles(epic, "MINUTE", 15)

        # Fetch Daily data for Gap context (5 points)
        candles_daily = await self.market_data.get_latest_candles(epic, "DAY", 5)

        if not candles_15m or len(candles_15m) < 20:
            logger.warning("Insufficient 15m data for analysis.")
            return None

        # Convert to DataFrame for Pandas TA
        df = pd.DataFrame([c.model_dump() for c in candles_15m])
        df.set_index("timestamp", inplace=True)

        # Calculate Indicators
        # Ensure we have float columns
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)

        try:
            df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
            df["RSI"] = ta.rsi(df["close"], length=14)
            df["EMA_20"] = ta.ema(df["close"], length=20)
        except Exception as e:
            logger.error(f"Indicator calculation error: {e}")
            return None

        latest = df.iloc[-1]

        # Volatility Logic
        current_atr = latest["ATR"] if pd.notna(latest["ATR"]) else 0.0
        avg_atr = df["ATR"].mean()
        vol_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0

        vol_regime = VolatilityRegime.MEDIUM
        if vol_ratio < 0.8:
            vol_regime = VolatilityRegime.LOW
        elif vol_ratio > 1.2:
            vol_regime = VolatilityRegime.HIGH

        # Trend Logic
        ema = latest["EMA_20"] if pd.notna(latest["EMA_20"]) else latest["close"]
        trend = TrendContext.BULLISH if latest["close"] > ema else TrendContext.BEARISH

        # Gap Logic
        prev_close = 0.0
        if candles_daily and len(candles_daily) >= 2:
            prev_close = candles_daily[-2].close
        elif len(candles_daily) == 1:
            prev_close = candles_daily[-1].open  # Fallback

        gap_pct = 0.0
        if prev_close > 0:
            gap_pct = ((latest["close"] - prev_close) / prev_close) * 100

        regime = MarketRegime(
            symbol=epic,
            timestamp=datetime.now(timezone.utc),
            current_price=latest["close"],
            daily_open=candles_daily[-1].open if candles_daily else latest["open"],
            prev_close=prev_close,
            atr_14=current_atr,
            avg_atr=avg_atr,
            volatility_ratio=vol_ratio,
            regime=vol_regime,
            ema_20=ema,
            trend=trend,
            rsi_14=latest["RSI"] if pd.notna(latest["RSI"]) else 50.0,
            gap_percent=gap_pct,
        )

        # Attach additional timeframes to the regime object dynamically
        setattr(regime, "candles_5m", candles_5m)
        setattr(regime, "candles_1m", candles_1m)
        setattr(regime, "candles_daily", candles_daily)

        return regime

    def _format_context(self, regime: MarketRegime, news: str) -> str:
        # Helper to format candles
        def fmt_candles(candles, limit=5):
            if not candles:
                return "No Data"
            # Format: Time | Open | High | Low | Close
            lines = ["Time (UTC) | Open | High | Low | Close"]
            for c in candles[-limit:]:
                ts = c.timestamp.strftime("%H:%M")
                lines.append(f"{ts} | {c.open} | {c.high} | {c.low} | {c.close}")
            return "\n".join(lines)

        context = f"""
        Instrument: {regime.symbol}
        Price: {regime.current_price}
        Trend: {regime.trend} (EMA20: {regime.ema_20:.2f})
        RSI: {regime.rsi_14:.2f}
        ATR: {regime.atr_14:.2f} (Avg: {regime.avg_atr:.2f})
        Volatility: {regime.regime} (Ratio: {regime.volatility_ratio:.2f})
        Gap: {regime.gap_percent:+.2f}%
        """

        if regime.candles_5m:
            context += f"\n\n--- 5-Minute Structure (Last 5) ---\n{fmt_candles(regime.candles_5m, 5)}"

        if regime.candles_1m:
            context += f"\n\n--- 1-Minute Timing (Last 5) ---\n{fmt_candles(regime.candles_1m, 5)}"

        if regime.candles_daily:
            lines = ["Date | Open | High | Low | Close"]
            for c in regime.candles_daily[-5:]:
                ts = c.timestamp.strftime("%Y-%m-%d")
                lines.append(f"{ts} | {c.open} | {c.high} | {c.low} | {c.close}")
            context += "\n\n--- Daily Context (Last 5) ---\n" + "\n".join(lines)

        context += f"\n\nNews Summary:\n{news}\n"
        return context

    async def _wait_for_trigger(
        self, epic: str, direction: str, target_entry: float
    ) -> Optional[float]:
        """
        Monitors stream until price touches the target entry.
        Returns the trigger price if hit, or None if timed out.
        """
        timeout = 5400  # 90 minutes wait time
        start_time = datetime.now(timezone.utc).timestamp()

        async for update in self.streamer.stream(epic):
            if (datetime.now(timezone.utc).timestamp() - start_time) > timeout:
                logger.info("Entry trigger timed out.")
                return None

            if update.get("type") == "price_update":
                bid = update.get("bid")
                offer = update.get("offer")
                if not bid or not offer:
                    continue

                # Check Trigger
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
        """
        Monitors an active position using the StreamerService and manages Trailing Stop.
        """
        logger.info(f"Starting Monitor for Deal {deal_id} (ATR: {atr})...")

        # Risk Management Rules
        trail_distance = atr * 1.5  # Keep stop 1.5 ATR away
        step_size = atr * 0.5  # Only move if we can improve by 0.5 ATR

        # Hard timeout (e.g., 2 hours)
        timeout = 7200
        start_time = datetime.now(timezone.utc).timestamp()

        async for update in self.streamer.stream(epic):
            if (datetime.now(timezone.utc).timestamp() - start_time) > timeout:
                logger.info("Monitor timeout reached. Stopping stream.")
                break

            if update.get("type") == "price_update":
                bid = update.get("bid")
                offer = update.get("offer")

                if not bid or not offer:
                    continue

                new_stop = None

                # Logic for BUY
                if direction == "BUY":
                    market_price = bid
                    target_stop = market_price - trail_distance
                    if target_stop > (current_stop + step_size):
                        new_stop = round(target_stop, 1)

                # Logic for SELL
                elif direction == "SELL":
                    market_price = offer
                    target_stop = market_price + trail_distance
                    if target_stop < (current_stop - step_size):
                        new_stop = round(target_stop, 1)

                if new_stop:
                    logger.info(
                        f"Trailing Stop Trigger: Price {bid if direction == 'BUY' else offer} -> New Stop {new_stop}"
                    )
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

    async def _update_execution_stop(self, deal_id: str, new_stop: float):
        async with async_session_maker() as session:
            stmt = select(TradeExecution).where(TradeExecution.deal_id == deal_id)
            result = await session.execute(stmt)
            execution = result.scalars().first()
            if execution:
                execution.current_stop_loss = new_stop
                session.add(execution)
                await session.commit()

    async def _save_signal(
        self, signal: TradingSignal, strategy_name: str
    ) -> TradeSignal:
        async with async_session_maker() as session:
            db_signal = TradeSignal(
                symbol=signal.ticker,
                strategy_name=strategy_name,
                signal_decision=signal.action.value,
                confidence=signal.confidence,
                reasoning=signal.reasoning,
                entry_price=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                position_size=signal.size,
                atr_at_generation=signal.atr,
            )
            session.add(db_signal)
            await session.commit()
            await session.refresh(db_signal)
            return db_signal

    async def _save_execution(
        self,
        signal_id: Optional[int],
        deal_id: str,
        direction: str,
        fill_price: float,
        size: float,
        stop_loss: float,
    ):
        async with async_session_maker() as session:
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

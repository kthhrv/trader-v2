import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.core.logger import logger
from app.core.markets import MARKET_CONFIGS
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService, TradingSignal, Action
from app.services.market_data import MarketDataService
from app.domain.models import MarketRegime, VolatilityRegime, TrendContext


class StrategyEngine:
    def __init__(
        self,
        ig_client: AsyncIGClient,
        market_data: MarketDataService,
        analyst: GeminiService,
        dry_run: bool = False,
    ):
        self.ig_client = ig_client
        self.market_data = market_data
        self.analyst = analyst
        self.dry_run = dry_run

    async def run_strategy(self, market_key: str):
        """
        Executes the 'Market Open' strategy for a specific market.
        """
        config = MARKET_CONFIGS.get(market_key)
        if not config:
            logger.error(f"Invalid market key: {market_key}")
            return

        epic = config["epic"]
        logger.info(f"Starting Strategy Run for {config['name']} ({epic})...")

        # 1. Build Market Regime (Technical Analysis)
        regime = await self._build_market_regime(epic)
        if not regime:
            logger.error("Failed to build market regime. Aborting.")
            return

        # 2. Fetch News (Placeholder for now, or use simple mock)
        # TODO: Port NewsFetcher or use a simplified version
        news_summary = "No news fetcher configured yet."

        # 3. Format Context for AI
        context_str = self._format_context(regime, news_summary)

        # 4. Get AI Analysis
        signal = await self.analyst.analyze_market(context_str)

        if not signal:
            logger.error("AI returned no signal.")
            return

        logger.info(f"AI Decision: {signal.action} | Conf: {signal.confidence}")

        if signal.action == Action.WAIT:
            return

        # 5. Execute (if not WAIT)
        await self._execute_signal(signal, epic)

    async def _build_market_regime(self, epic: str) -> Optional[MarketRegime]:
        """
        Fetches data and calculates indicators to form the Market Regime.
        """
        # Fetch 15m data for indicators (50 points)
        candles_15m = await self.market_data.get_latest_candles(epic, "MIN_15", 50)

        # Fetch Daily data for Gap context (5 points)
        candles_daily = await self.market_data.get_latest_candles(epic, "D", 5)

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

        return MarketRegime(
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

    def _format_context(self, regime: MarketRegime, news: str) -> str:
        return f"""
        Instrument: {regime.symbol}
        Price: {regime.current_price}
        Trend: {regime.trend} (EMA20: {regime.ema_20:.2f})
        RSI: {regime.rsi_14:.2f}
        ATR: {regime.atr_14:.2f} (Avg: {regime.avg_atr:.2f})
        Volatility: {regime.regime} (Ratio: {regime.volatility_ratio:.2f})
        Gap: {regime.gap_percent:+.2f}%
        
        News Summary:
        {news}
        """

    async def _execute_signal(self, signal: TradingSignal, epic: str):
        """
        Executes the trade via IG Client.
        """
        logger.info(f"Executing {signal.action} for {epic}...")

        if self.dry_run:
            logger.info("DRY RUN: Trade simulation successful.")
            return

        direction = "BUY" if signal.action == Action.BUY else "SELL"

        try:
            # Note: We rely on the client to handle the order placement
            # We might want to add size calc logic here or in client
            # For now using signal size directly

            response = await self.ig_client.create_order(
                epic=epic,
                direction=direction,
                size=signal.size,
                stop_level=signal.stop_loss,
                limit_level=signal.take_profit,
                env_type=settings.TRADING_ACCOUNT_ENV,
            )
            logger.info(f"Order Placed: {response}")

        except Exception as e:
            logger.error(f"Execution Failed: {e}")

import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone
from typing import Optional

from app.core.logger import logger
from app.services.market_data import MarketDataService
from app.adapters.news_client import NewsClient
from app.adapters.gemini_service import GeminiService, TradingSignal
from app.domain.models import MarketRegime, VolatilityRegime, TrendContext


class MarketAnalyzer:
    def __init__(
        self,
        market_data: MarketDataService,
        news_client: NewsClient,
        gemini: GeminiService,
    ):
        self.market_data = market_data
        self.news_client = news_client
        self.gemini = gemini

    async def analyze_market(
        self, market_key: str, config: dict
    ) -> Optional[TradingSignal]:
        """
        Full analysis pipeline: Data -> Indicators -> News -> AI -> Signal.
        """
        epic = config["epic"]

        # 1. Build Regime
        regime = await self._build_market_regime(epic)
        if not regime:
            logger.error("Failed to build market regime.")
            return None

        # 2. Fetch News
        news_query = self._get_news_query(epic)
        logger.info(f"Fetching news for query: {news_query}")
        news_summary = await self.news_client.fetch_news(news_query, market=market_key)

        # 3. Format Context
        context_str = self._format_context(regime, news_summary)

        # 4. AI Analysis
        signal = await self.gemini.analyze_market(context_str)
        return signal

    async def _build_market_regime(self, epic: str) -> Optional[MarketRegime]:
        # Fetch Data
        candles_15m = await self.market_data.get_latest_candles(epic, "MINUTE_15", 50)
        candles_5m = await self.market_data.get_latest_candles(epic, "MINUTE_5", 24)
        candles_1m = await self.market_data.get_latest_candles(epic, "MINUTE", 15)
        candles_daily = await self.market_data.get_latest_candles(epic, "DAY", 5)

        if not candles_15m or len(candles_15m) < 20:
            logger.warning("Insufficient 15m data for analysis.")
            return None

        # Indicators
        df = pd.DataFrame([c.model_dump() for c in candles_15m])
        df.set_index("timestamp", inplace=True)
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

        # Logic
        current_atr = latest["ATR"] if pd.notna(latest["ATR"]) else 0.0
        avg_atr = df["ATR"].mean()
        vol_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0

        vol_regime = VolatilityRegime.MEDIUM
        if vol_ratio < 0.8:
            vol_regime = VolatilityRegime.LOW
        elif vol_ratio > 1.2:
            vol_regime = VolatilityRegime.HIGH

        ema = latest["EMA_20"] if pd.notna(latest["EMA_20"]) else latest["close"]
        trend = TrendContext.BULLISH if latest["close"] > ema else TrendContext.BEARISH

        prev_close = 0.0
        if candles_daily and len(candles_daily) >= 2:
            prev_close = candles_daily[-2].close
        elif len(candles_daily) == 1:
            prev_close = candles_daily[-1].open

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
            candles_5m=candles_5m,
            candles_1m=candles_1m,
            candles_daily=candles_daily,
        )
        return regime

    def _format_context(self, regime: MarketRegime, news: str) -> str:
        def fmt_candles(candles, limit=5):
            if not candles:
                return "No Data"
            lines = ["Time (UTC) | Open | High | Low | Close"]
            for c in candles[-limit:]:
                ts = c.timestamp.strftime("%H:%M")
                lines.append(f"{ts} | {c.open} | {c.high} | {c.low} | {c.close}")
            return "\\n".join(lines)

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
            context += f"\\n\\n--- 5-Minute Structure (Last 5) ---\\n{fmt_candles(regime.candles_5m, 5)}"
        if regime.candles_1m:
            context += f"\\n\\n--- 1-Minute Timing (Last 5) ---\\n{fmt_candles(regime.candles_1m, 5)}"
        if regime.candles_daily:
            lines = ["Date | Open | High | Low | Close"]
            for c in regime.candles_daily[-5:]:
                ts = c.timestamp.strftime("%Y-%m-%d")
                lines.append(f"{ts} | {c.open} | {c.high} | {c.low} | {c.close}")
            context += "\\n\\n--- Daily Context (Last 5) ---\\n" + "\\n".join(lines)

        context += f"\\n\\nNews Summary:\\n{news}\\n"
        return context

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

import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone
from typing import Optional

from app.core.logger import logger
from app.services.market_data import MarketDataService
from app.adapters.news_client import NewsClient
from app.adapters.gemini_service import GeminiService, TradingSignal
from app.core.prompts import STRATEGY_PROMPTS
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
        strategy_id = config.get("strategy_id", "momentum_breakout")
        instruction = STRATEGY_PROMPTS.get(
            strategy_id, STRATEGY_PROMPTS["momentum_breakout"]
        )
        signal = await self.gemini.analyze_market(context_str, instruction)
        return signal

    async def _build_market_regime(self, epic: str) -> Optional[MarketRegime]:
        # Fetch Data
        candles_15m = await self.market_data.get_latest_candles(epic, "MINUTE_15", 50)
        candles_5m = await self.market_data.get_latest_candles(epic, "MINUTE_5", 24)
        candles_1m = await self.market_data.get_latest_candles(epic, "MINUTE", 15)
        # Increase daily history to 10 days to match V1
        candles_daily = await self.market_data.get_latest_candles(epic, "DAY", 10)

        if not candles_15m or len(candles_15m) < 20:
            logger.warning("Insufficient 15m data for analysis.")
            return None

        # Fetch External Factors (VIX / Sentiment)
        vix_level = await self.market_data.get_vix_level()
        sentiment = await self.market_data.get_client_sentiment(epic)

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

        # Format Trend Table (Last 50 periods with indicators)
        # We simplify the columns to save tokens while keeping indicators
        table_cols = ["open", "high", "low", "close", "volume", "RSI", "ATR", "EMA_20"]
        # Ensure we only use columns that exist
        available_cols = [c for c in table_cols if c in df.columns]
        # Format index to show only HH:MM for clarity
        df.index = pd.to_datetime(df.index)
        display_df = df[available_cols].tail(50).copy()
        display_df.index = display_df.index.strftime("%H:%M")
        trend_table = display_df.to_string()

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
            # Use second to last for prev close if today is included
            # IG 'DAY' candle is today's live candle if market open.
            prev_close = candles_daily[-2].close
        elif len(candles_daily) == 1:
            prev_close = candles_daily[-1].open

        gap_pct = 0.0
        if prev_close > 0:
            gap_pct = ((latest["close"] - prev_close) / prev_close) * 100

        # Session Extremes (Today's High/Low)
        # We can approximate this from the 15m/5m/1m data we have if they cover the session.
        # But simpler is to assume 'candles_daily[-1]' is TODAY's candle if timestamp matches today.
        session_high = None
        session_low = None

        if candles_daily:
            today_candle = candles_daily[-1]
            # Simple check if date matches
            if today_candle.timestamp.date() == datetime.now(timezone.utc).date():
                session_high = today_candle.high
                session_low = today_candle.low

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
            vix_level=vix_level,
            client_sentiment=sentiment,
            session_high=session_high,
            session_low=session_low,
            trend_table=trend_table,
        )
        return regime

    def _format_context(self, regime: MarketRegime, news: str) -> str:
        def fmt_candles(candles, limit=5):
            if not candles:
                return "No Data"
            lines = ["Time (UTC) | Open | High | Low | Close | Vol"]
            for c in candles[-limit:]:
                ts = c.timestamp.strftime("%H:%M")
                vol = getattr(c, "volume", 0) or 0
                lines.append(
                    f"{ts} | {c.open} | {c.high} | {c.low} | {c.close} | {int(vol)}"
                )
            return "\\n".join(lines)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        context = f"""
        Current Time (UTC): {now_utc}
        Instrument: {regime.symbol}
        Price: {regime.current_price}
        Trend: {regime.trend} (EMA20: {regime.ema_20:.2f})
        RSI: {regime.rsi_14:.2f}
        ATR: {regime.atr_14:.2f} (Avg: {regime.avg_atr:.2f})
        Volatility: {regime.regime} (Ratio: {regime.volatility_ratio:.2f})
        Gap: {regime.gap_percent:+.2f}%
        """

        if regime.vix_level:
            context += f"\\nVIX Level: {regime.vix_level} (Market Fear Index)"

        if regime.client_sentiment:
            longs = regime.client_sentiment.get("long", 0)
            shorts = regime.client_sentiment.get("short", 0)
            context += f"\\nClient Sentiment: Long {longs}% | Short {shorts}%"
            if longs > 70:
                context += " (Crowded Long - Bearish Contra)"
            elif shorts > 70:
                context += " (Crowded Short - Bullish Contra)"

        if regime.session_high is not None and regime.session_low is not None:
            context += f"\\nSession Range: Low {regime.session_low} - High {regime.session_high}"
            if regime.session_high != regime.session_low:
                pos = (
                    (regime.current_price - regime.session_low)
                    / (regime.session_high - regime.session_low)
                ) * 100
                context += f" (Position: {pos:.0f}%)"

        if regime.trend_table:
            context += f"\\n\\n--- Recent Trend Data (Last 12 Hours, 15m intervals) ---\\n{regime.trend_table}"

        if regime.candles_5m:
            context += f"\\n\\n--- 5-Minute Structure (Last 2 Hours) ---\\n{fmt_candles(regime.candles_5m, 24)}"
        if regime.candles_1m:
            context += f"\\n\\n--- 1-Minute Timing (Last 15 Mins) ---\\n{fmt_candles(regime.candles_1m, 15)}"

        if regime.candles_daily:
            lines = ["Date | Open | High | Low | Close | Vol"]
            for c in regime.candles_daily[-10:]:
                ts = c.timestamp.strftime("%Y-%m-%d")
                vol = getattr(c, "volume", 0) or 0
                lines.append(
                    f"{ts} | {c.open} | {c.high} | {c.low} | {c.close} | {int(vol)}"
                )
            context += "\\n\\n--- Daily Context (Last 10 Days) ---\\n" + "\\n".join(
                lines
            )

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

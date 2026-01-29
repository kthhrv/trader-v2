import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from app.core.logger import logger
from app.services.market_data import MarketDataService
from app.services.technical_analysis import TechnicalAnalysisService
from app.adapters.news_client import NewsClient
from app.adapters.gemini_service import GeminiService, TradingSignal
from app.core.prompts import STRATEGY_PROMPTS
from app.domain.models import (
    MarketRegime,
    VolatilityRegime,
    TrendContext,
    MarketIndicators,
    MarketState,
)


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
        # TechnicalAnalysisService is static, no instance needed

    async def analyze_market(
        self, market_key: str, config: dict, override_strategy: Optional[str] = None
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
        if override_strategy:
            selected_strategy = override_strategy
            logger.info(f"Strategy Override Active: {selected_strategy}")
        else:
            default_strategy = config.get("strategy_id", "momentum_breakout")
            selected_strategy = self._determine_strategy(
                regime, default_strategy, config
            )
            logger.info(
                f"Strategy Selected: {selected_strategy} (Default: {default_strategy})"
            )

        instruction = STRATEGY_PROMPTS.get(
            selected_strategy, STRATEGY_PROMPTS["momentum_breakout"]
        )
        signal = await self.gemini.analyze_market(context_str, instruction)
        return signal

    def _determine_strategy(
        self, regime: MarketRegime, default_id: str, config: dict
    ) -> str:
        """
        Selects the best strategy based on Market Regime (V3 Logic Matrix).
        Hierarchy: Time -> Risk -> Technical.
        """
        # 1. TIER 1: TEMPORAL OVERRIDE (The Open)
        # If we are within -15m to +30m of the scheduled open, force default (usually us_volatility).
        schedule = config.get("schedule")
        market_tz = config.get("timezone", "UTC")

        if schedule:
            import pytz

            now_localized = datetime.now(pytz.timezone(market_tz))
            market_open = now_localized.replace(
                hour=schedule["hour"],
                minute=schedule["minute"],
                second=0,
                microsecond=0,
            )
            # -15 mins to +30 mins
            time_since_open = (now_localized - market_open).total_seconds()
            if -900 <= time_since_open <= 1800:
                logger.info(
                    f"Market Open Phase ({int(time_since_open / 60)}m relative to open). Forcing Open Strategy."
                )
                return default_id

        # 2. TIER 2: SAFETY OVERRIDE (Parabolic/Climax)
        if regime.state.is_parabolic:
            logger.info("Regime is PARABOLIC. Switching to Climax Reversal.")
            return "climax_reversal"

        # 3. TIER 3: TECHNICAL REGIME (Mid-Session)
        # Choppy / Low Energy -> Mean Reversion
        if regime.state.is_choppy:
            return "mean_reversion"

        # Default -> Trend/Breakout
        return default_id

    async def _build_market_regime(self, epic: str) -> Optional[MarketRegime]:
        # Fetch Data
        candles_15m = await self.market_data.get_latest_candles(epic, "MINUTE_15", 50)
        candles_5m = await self.market_data.get_latest_candles(epic, "MINUTE_5", 24)
        candles_1m = await self.market_data.get_latest_candles(epic, "MINUTE", 15)
        candles_daily = await self.market_data.get_latest_candles(epic, "DAY", 10)

        if not candles_15m or len(candles_15m) < 20:
            logger.warning("Insufficient 15m data for analysis.")
            return None

        # Fetch External Factors
        vix_level = await self.market_data.get_vix_level()
        sentiment = await self.market_data.get_client_sentiment(epic)

        # 1. Prepare Data
        df = pd.DataFrame([c.model_dump() for c in candles_15m])
        df.set_index("timestamp", inplace=True)

        # 2. Calculate Indicators (Delegated)
        df = TechnicalAnalysisService.calculate_indicators(df)

        # 3. Calculate V3 Metrics
        rvol = TechnicalAnalysisService.calculate_rvol(df)
        slope = TechnicalAnalysisService.calculate_slope(df)

        latest = df.iloc[-1]

        # 4. Derived Values & Classification
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

        # Parabolic Check: Distance from EMA > 2.5x ATR
        extension = 0.0
        if current_atr > 0:
            extension = (latest["close"] - ema) / current_atr

        is_parabolic = abs(extension) > 2.5

        # Choppy Check: ADX < 20 OR Low Volatility
        adx = latest["ADX"] if pd.notna(latest["ADX"]) else 0.0
        is_choppy = (adx < 20) or (vol_ratio < 0.8)

        # Session & Gap Logic
        prev_close = 0.0
        if candles_daily and len(candles_daily) >= 2:
            prev_close = candles_daily[-2].close
        elif len(candles_daily) == 1:
            prev_close = candles_daily[-1].open

        live_price = latest["close"]
        if candles_1m and len(candles_1m) > 0:
            live_price = candles_1m[-1].close

        gap_pct = 0.0
        if prev_close > 0:
            gap_pct = ((live_price - prev_close) / prev_close) * 100

        session_high = None
        session_low = None
        if candles_daily:
            today_candle = candles_daily[-1]
            if today_candle.timestamp.date() == datetime.now(timezone.utc).date():
                session_high = today_candle.high
                session_low = today_candle.low

        # 5. Format Trend Table
        table_cols = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "RSI",
            "ATR",
            "ADX",
            "EMA_20",
        ]
        available_cols = [c for c in table_cols if c in df.columns]
        # We need to preserve the dataframe for display but keep the original logic clean
        display_df = df[available_cols].tail(50).copy()
        display_df.index = pd.to_datetime(display_df.index).strftime("%H:%M")
        trend_table = display_df.to_string()

        # 6. Construct Nested Models
        indicators = MarketIndicators(
            atr_14=current_atr,
            avg_atr=avg_atr,
            rsi_14=latest["RSI"] if pd.notna(latest["RSI"]) else 50.0,
            adx_14=adx,
            ema_20=ema,
            rvol=rvol,
            ema_slope=slope,
            extension_factor=extension,
        )

        state = MarketState(
            trend=trend,
            volatility=vol_regime,
            volatility_ratio=vol_ratio,
            is_parabolic=is_parabolic,
            is_choppy=is_choppy,
        )

        regime = MarketRegime(
            symbol=epic,
            timestamp=datetime.now(timezone.utc),
            current_price=live_price,
            daily_open=candles_daily[-1].open if candles_daily else latest["open"],
            prev_close=prev_close,
            gap_percent=gap_pct,
            session_high=session_high,
            session_low=session_low,
            indicators=indicators,
            state=state,
            vix_level=vix_level,
            client_sentiment=sentiment,
            candles_5m=candles_5m,
            candles_1m=candles_1m,
            candles_daily=candles_daily,
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

        # Access nested properties
        ind = regime.indicators
        st = regime.state

        context = f"""
        Current Time (UTC): {now_utc}
        Instrument: {regime.symbol}
        Price: {regime.current_price}
        Trend: {st.trend} (EMA20: {ind.ema_20:.2f} | Slope: {ind.ema_slope:.3f})
        RSI: {ind.rsi_14:.2f}
        ADX: {ind.adx_14:.2f} (Strength: {"Strong" if (ind.adx_14 or 0) > 25 else "Weak"})
        ATR: {ind.atr_14:.2f} (Avg: {ind.avg_atr:.2f})
        Volatility: {st.volatility} (Ratio: {st.volatility_ratio:.2f})
        Volume: RVOL {ind.rvol:.2f} (Relative to 20p Avg)
        Condition: {"PARABOLIC" if st.is_parabolic else "Normal"} (Extension: {ind.extension_factor:.2f}x ATR)
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

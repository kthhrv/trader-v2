import pandas as pd
import pandas_ta as ta


class TechnicalAnalysisService:
    """
    Encapsulates technical indicator calculations using pandas-ta.
    """

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates standard indicators (ATR, RSI, EMA, ADX) inplace.
        Expects index to be datetime.
        """
        if df.empty:
            return df

        # Ensure types
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        # Volume might be int or float
        if "volume" in df.columns:
            df["volume"] = df["volume"].astype(float)

        # 1. Standard Indicators
        try:
            df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
            df["RSI"] = ta.rsi(df["close"], length=14)
            df["EMA_20"] = ta.ema(df["close"], length=20)

            # ADX (Returns DataFrame)
            adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
            if adx_df is not None and "ADX_14" in adx_df.columns:
                df["ADX"] = adx_df["ADX_14"]
            else:
                df["ADX"] = 0.0

        except Exception:
            # Fail gracefully, caller checks for NaN
            pass

        return df

    @staticmethod
    def calculate_rvol(df: pd.DataFrame, window: int = 20) -> float:
        """
        Calculates Relative Volume (RVOL) for the latest candle.
        RVOL = Current Volume / Average Volume (last N periods).
        """
        if "volume" not in df.columns or len(df) < window:
            return 1.0

        current_vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].rolling(window=window).mean().iloc[-1]

        if avg_vol > 0:
            return float(current_vol / avg_vol)
        return 1.0

    @staticmethod
    def calculate_slope(df: pd.DataFrame) -> float:
        """
        Calculates the slope of the EMA (Angle).
        Metric: (EMA[0] - EMA[1]) / ATR.
        Positive = Uptrend, Negative = Downtrend.
        """
        if "EMA_20" not in df.columns or "ATR" not in df.columns or len(df) < 2:
            return 0.0

        ema_now = df["EMA_20"].iloc[-1]
        ema_prev = df["EMA_20"].iloc[-2]
        atr = df["ATR"].iloc[-1]

        if pd.isna(ema_now) or pd.isna(ema_prev) or pd.isna(atr):
            return 0.0

        if atr > 0:
            return float((ema_now - ema_prev) / atr)
        return 0.0

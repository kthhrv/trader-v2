# Plan: Market Regime V3 Enhancements

## Objective
Upgrade the `MarketAnalyzer` and `MarketRegime` models to move beyond simple binary trend definitions (Bullish/Bearish) and incorporate volume and momentum nuances. This will help the AI distinguish between "Healthy Trends," "Parabolic Climaxes," and "Volume-Supported Breakouts."

## 1. Relative Volume (RVOL)
**Why:** Volume is the "lie detector" of price. A breakout on low volume is often a trap. A move on 2x average volume is institutional participation.
**Implementation:**
- Calculate the average volume for the current time-of-day (to account for opening/closing auctions).
- **Metric:** `RVOL = Current Volume / Average Volume (20 period)`
- **Logic:**
    - `RVOL > 1.5`: High participation (Validates Breakouts).
    - `RVOL < 0.8`: Low participation (Suspect moves).

## 2. Advanced Trend Definition (EMA Slope)
**Why:** `Price > EMA` is insufficient. If the EMA is flat, the market is ranging, even if price is slightly above it.
**Implementation:**
- Calculate the angle/slope of the 20-period EMA.
- **Metric:** `EMA_Slope = (EMA[0] - EMA[1]) / ATR`
- **Logic:**
    - `Slope > 0.1`: Strong Uptrend.
    - `Slope < -0.1`: Strong Downtrend.
    - `Between -0.1 and 0.1`: Consolidation/Flat.

## 3. "Parabolic" / Overextended Regime
**Why:** To prevent buying at the top of a climax run or selling at the bottom of a crash (the "Vertical Candle" problem).
**Implementation:**
- Measure distance between Price and EMA20.
- **Metric:** `Extension = (Price - EMA20) / ATR`
- **Logic:**
    - `Extension > 2.0`: Overbought / Parabolic (Look to tighten stops or fade).
    - `Extension < -2.0`: Oversold / Crash (Do not chase).

## 4. Updates to `MarketRegime` Model
Update `app/domain/models.py` to include:
```python
class MarketRegime(BaseModel):
    # ... existing fields ...
    rvol: float = 1.0
    ema_slope: float = 0.0
    extension_factor: float = 0.0  # (Price - EMA) / ATR
    is_parabolic: bool = False
```

## 5. Updates to `MarketAnalyzer` (`app/services/analyzer.py`)
- Implement `_calculate_rvol()` using `candles_15m`.
- Implement `_calculate_slope()` using pandas_ta or simple diff.
- Populate new fields in `_build_market_regime`.
- Update `_format_context` to expose these new metrics to the LLM.

## 6. Updates to Prompts (`app/core/prompts.py`)
- Instruct the AI to use `RVOL` to validate breakouts.
- Instruct the AI to treat `is_parabolic` as a warning to NOT enter new positions (or switch to "Pullback" only).

## Success Criteria
- The AI correctly identifies "Low Volume Breakouts" and avoids them.
- The AI recognizes "Parabolic" moves and switches to defensive logic automatically.

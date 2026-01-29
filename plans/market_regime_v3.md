# Plan: Market Regime V3 Enhancements

## Objective
Upgrade the `MarketAnalyzer` and `MarketRegime` models to move beyond simple binary trend definitions (Bullish/Bearish) and incorporate volume and momentum nuances. This will help the AI distinguish between "Healthy Trends," "Parabolic Climaxes," and "Volume-Supported Breakouts."

## 1. Relative Volume (RVOL) [DONE]
- Implementation in `TechnicalAnalysisService.calculate_rvol`.

## 2. Advanced Trend Definition (EMA Slope) [DONE]
- Implementation in `TechnicalAnalysisService.calculate_slope`.

## 3. "Parabolic" / Overextended Regime [DONE]
- Implementation in `MarketAnalyzer._build_market_regime`.
- **Threshold:** 2.5x ATR.

## 4. Updates to `MarketRegime` Model (Nested Structure) [DONE]
- Implementation in `app/domain/models.py`.

## 5. Updates to MarketAnalyzer (`app/services/analyzer.py`) [DONE]
- Delegated math to TA service.
- Formatted new metrics into AI context.

## 6. Updates to Prompts (`app/core/prompts.py`) [DONE]
- Added `STRAT_CLIMAX_REVERSAL` for parabolic events.
- Updated `STRAT_US_VOLATILITY` with catalyst awareness.

## Success Criteria
- [x] AI identifies "Low Volume Breakouts".
- [x] AI recognizes "Parabolic" moves via new persona.
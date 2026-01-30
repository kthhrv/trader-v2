# Plan: Trust the Sentinel (High-Frequency Override)

## Problem
The **Sentinel** monitors 1-minute candles and detects "Parabolic Extensions" (overextended moves). However, the **Analyzer** uses 15-minute candles to build the market regime.
- **The Bug:** A sharp 1m crash triggers the Sentinel (`PARABOLIC_EXT_2.6x`). The Analyzer wakes up, looks at the 15m chart, sees the price is only slightly below the 15m EMA, and decides "Extension is normal (0.15x)".
- **The Result:** The bot enters a "Momentum Breakout" (selling at the bottom of a crash) instead of switching to "Climax Reversal" mode.

## Objective
Ensure the `MarketAnalyzer` trusts the Sentinel's trigger reason. If the Sentinel says it is PARABOLIC, the Analyzer must treat it as a CLIMAX event regardless of what the 15m chart says.

## Implementation Steps

### 1. Update Analyzer Signature
- Modify `_build_market_regime(self, epic: str)` to `_build_market_regime(self, epic: str, trigger_source: str = "unknown")`.

### 2. Implement Force-State Logic
- Inside `_build_market_regime`:
    - After calculating standard indicators, check the `trigger_source`.
    - If `"PARABOLIC"` is in `trigger_source`:
        - Force `state.is_parabolic = True`.
        - Set `indicators.extension_factor` to the value provided in the trigger (or a safe default > 2.5).

### 3. Strategy Selection Flow
- The existing Waterfall Logic in `_determine_strategy` already handles `is_parabolic`:
    ```python
    if regime.state.is_parabolic:
        return "climax_reversal"
    ```
- By forcing the state in Step 2, the AI will now automatically receive the `STRAT_CLIMAX_REVERSAL` prompt (Contrarian Persona), which instructs it to **Wait** or **Fade**, preventing it from "Chasing the Knife."

### 4. Verification
- **Unit Test:** Pass `trigger_source="sentinel_PARABOLIC_EXT_3.0x"` to the Analyzer with "calm" 15m data.
- **Expected Result:** `selected_strategy` should be `"climax_reversal"`.

## Outcome
The bot will no longer "Sell the Lows" or "Buy the Highs" during Sentinel Parabolic events. It will correctly identify these as high-risk climax events and switch to a defensive/contrarian posture.

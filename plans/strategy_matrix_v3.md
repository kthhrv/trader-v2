# Strategy Matrix V3: Logic Hierarchy

## Core Philosophy
The Strategy Engine selects the active "Agent Persona" (Prompt) based on a strict hierarchy of overrides.

## 1. The Override Hierarchy (Decision Tree) [DONE]
Implemented in `MarketAnalyzer._determine_strategy`:
1.  **Tier 1: Temporal (Open)** -> `us_volatility`
2.  **Tier 2: Safety (Parabolic)** -> `climax_reversal`
3.  **Tier 3: Technical (Mid-Session)** -> `momentum_breakout` / `mean_reversion`

## 2. Strategy Definitions (The "Modes") [DONE]
- Added `STRAT_CLIMAX_REVERSAL`.
- Updated `STRAT_US_VOLATILITY`.

## 3. Implementation Plan
1.  [x] **Analyzer Update:** Implemented Tier 1 -> 2 -> 3 waterfall.
2.  [x] **Prompt Creation:** Created `STRAT_CLIMAX_REVERSAL`.
3.  [x] **Regime Integration:** Integrated `rvol`, `slope`, `is_parabolic`.
# Implementation Plan: Multi-Timeframe Trend Alignment

## Phase 1: Data Model & Core Logic
Update the domain models and implement the alignment calculation logic.

- [ ] Task: Define `TrendAlignment` enum and update `MarketState` model in `app/domain/models.py`.
    - [ ] Add `TrendAlignment` enum (BULLISH_CONFLUENCE, BEARISH_CONFLUENCE, DIVERGENT).
    - [ ] Add `trend_alignment` field to `MarketState` class.
- [ ] Task: Implement alignment calculation logic in `MarketAnalyzer`.
    - [ ] Write unit tests for `_calculate_trend_alignment` in `tests/services/test_analyzer_logic.py`.
    - [ ] Implement `_calculate_trend_alignment` method in `MarketAnalyzer`.
    - [ ] Update `_build_market_regime` to use the new calculation.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Data Model & Core Logic' (Protocol in workflow.md)

## Phase 2: Integration & Formatting
Expose the alignment data to the AI Analyst through prompt context.

- [ ] Task: Update `MarketAnalyzer._format_context` to include trend alignment.
    - [ ] Write unit test for context formatting.
    - [ ] Update `_format_context` implementation to include a clear "Trend Alignment" section.
- [ ] Task: Verify E2E regime analysis output.
    - [ ] Run `python main.py --market asx --regime` and verify the new field appears correctly.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Integration & Formatting' (Protocol in workflow.md)

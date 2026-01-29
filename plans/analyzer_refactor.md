# Plan: Analyzer Refactor

## Objective
The `MarketAnalyzer` has become a "God Class," mixing data orchestration, technical analysis math, business logic, and prompt formatting. Before adding V3 features (RVOL, EMA Slope, Parabolic), we must refactor the codebase to separate these concerns.

## 1. Extract Technical Analysis [DONE]
**Solution:** Created `app/services/technical_analysis.py`.
- **Class:** `TechnicalAnalysisService`
- **Methods Implemented:** `calculate_indicators`, `calculate_rvol`, `calculate_slope`.

## 2. Refactor Data Models [DONE]
**Solution:** Updated `app/domain/models.py` with nested Pydantic models.
- `MarketIndicators`, `MarketState`, `MarketRegime` (Nested).

## 3. Decouple Prompt Formatting [PARTIAL]
**Current Status:** `_format_context` was significantly cleaned and modernized in `Analyzer.py`, but not yet moved to a standalone `ContextBuilder` class. 

## 4. Simplified Analyzer Flow [DONE]
**Current Status:** `analyze_market` and `_build_market_regime` now use the delegated TA service and nested models.

## Execution Order
1.  [x] **Create `app/services/technical_analysis.py`**
2.  [x] **Update `app/domain/models.py`**
3.  [x] **Refactor `app/services/analyzer.py`**
4.  [ ] **Extract `ContextBuilder`** (Lower priority, can be done later).
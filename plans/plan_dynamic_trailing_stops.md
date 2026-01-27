# Plan: Dynamic Trailing Stops per Strategy

**Objective:** Allow the Trading Strategy (Momentum, Mean Reversion, etc.) and the AI Analyst to dictate the parameters for Trailing Stops and Breakeven triggers, rather than using hardcoded defaults in the Executor.

## Why?
- **Strategy Variance:**
    - **Momentum:** Needs tight trails (1.5x - 2x ATR) to lock in fast profits before reversals.
    - **Trend Following:** Needs loose trails (3x ATR) to ride fluctuations.
    - **Mean Reversion:** Often needs NO trail (fixed target) or a very tight one once mean is reached.
- **Current Limitation:** `TradeExecutor` uses hardcoded `trail_distance = 3.0 * ATR` and `breakeven_trigger = 1.5 * Risk`.

---

## Architecture Changes

### 1. Data Model (`app/adapters/gemini_service.py`)
- Update `TradingSignal` class to include optional fields:
    - `trailing_stop_atr_multiplier`: float (default 3.0)
    - `breakeven_trigger_r`: float (default 1.5)
    - `use_breakeven`: bool (default True)

### 2. Config (`app/core/markets.py`)
- Update `MARKET_CONFIGS` to allow overriding these defaults per market/strategy.
    - Example: `ftse` might default to 2.0x ATR, while `spx` defaults to 3.0x ATR.

### 3. AI Prompts (`app/core/prompts.py`)
- Update `STRATEGY_PROMPTS` to instruct the AI to output these parameters if it sees fit.
    - Example: "If volatility is extreme, tighten trailing stop to 1.5x ATR."

### 4. Execution Logic (`app/services/executor.py`)
- Update `_monitor_position` to read these values from the `TradingSignal` (passed via `TradeExecution` or stored in `TradeSignal` DB table).
- Since `TradeExecutor` reads from DB after restart, we need to persist these params in the `trade_signals` table or `trade_executions` table.

## Implementation Steps

### Phase 1: Database & Models
1. [ ] Migration: Add columns to `trade_signals` table: `trail_atr_mult`, `breakeven_r`.
2. [ ] Update `TradingSignal` Pydantic model.

### Phase 2: Logic
3. [ ] Update `MarketAnalyzer` to pass config defaults if AI doesn't specify.
4. [ ] Update `TradeExecutor._monitor_position` to use the dynamic values.

### Phase 3: Testing
5. [ ] Create unit test verifying different multiplier effects on stop movement.

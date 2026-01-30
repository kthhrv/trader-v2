# Plan: Active Trade Management (Garbage Collection & Dynamic Stops)

## Objective
Upgrade the Trader from "Fire and Forget" to "Active Management" by utilizing Sentinel triggers to invalidate stale plans and protect open profits without "smothering" trades with noise.

## Core Components

### 1. Plan Garbage Collection (Pending Orders)
**Problem:** A "Stalking" plan or pending Limit Order remains active even after the market structure has fundamentally changed (e.g., a crash while waiting to buy).
**Solution:** The Stalking Loop will listen for Sentinel Events to "Invalidate the Thesis".

*   **Logic:**
    *   If `Stalking_Direction == BUY` AND `Sentinel == PARABOLIC_BEARISH`: **CANCEL**.
    *   If `Stalking_Direction == SELL` AND `Sentinel == PARABOLIC_BULLISH`: **CANCEL**.
*   **Implementation:**
    *   **Dependency:** Requires `plans/plan_lifecycle_refactor.md` (Unified Streamer).
    *   Update `TradeExecutor._wait_for_trigger` to handle `SENTINEL` events from the event stream.
    *   If a conflicting High-Severity trigger occurs, abort the loop and log "Thesis Invalidation".

### 2. Dynamic Profit Protection (Live Trades)
**Problem:** A winning trade (e.g., +3R) gives back significant profit because the trailing stop is loose (1.5x ATR), even when the Sentinel identifies a clear reversal event.
**Solution:** Use "Regime-Based" Trailing Stops triggered by the Event Bus.

*   **Logic:**
    *   **Pre-Requisite:** Trade must be profitable (e.g., > 1.0R). (Don't tighten stops on a losing trade, that guarantees a loss).
    *   **Trigger:** Event Stream yields `SENTINEL` type with `PARABOLIC` or `RVOL_SPIKE`.
    *   **Action:** **Tighten Stop**.
        *   **Standard Mode:** `Trail = Price - (1.5 * ATR)`
        *   **Panic Mode:** `Trail = Price - (0.5 * ATR)` OR `Trail = Previous_Candle_Low`.
*   **Implementation:**
    *   Update `TradeExecutor._monitor_trade`.
    *   Listen for `SENTINEL` events in the main loop.
    *   If Trigger matches invalidation criteria:
        *   Calculate `New_Stop`.
        *   If `New_Stop` > `Current_Stop` (for Buy): **Update Order**.

## Execution Steps

1.  **Refactor Prerequisites:** Complete `plans/plan_lifecycle_refactor.md` to enable the Unified Event Bus.
2.  **Implement Stalking Logic:** Update `TradeExecutor._wait_for_trigger` to consume and act on Sentinel events.
3.  **Implement Monitor Logic:** Update `TradeExecutor._monitor_position` to consume and act on Sentinel events for dynamic stops.
4.  **Config:** Add `DYNAMIC_STOP_TRIGGER_R` (e.g., 1.0) to config. Only tighten if PnL > this amount.

## Outcome
*   **Reduced Drawdown:** Open profits are locked in faster during crashes.
*   **Fewer Bad Entries:** Stale plans are cancelled before they can trigger losses.

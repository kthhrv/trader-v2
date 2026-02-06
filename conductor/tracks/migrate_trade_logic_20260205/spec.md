# Specification: Migrate Active Trade Logic to TradeActor

## Overview
Currently, `TradeExecutor` manages the logic for when to move a stop loss to breakeven or how to trail it based on ATR. While `TradeActor` now tracks these state transitions, it doesn't "own" the logic that triggers them. This track moves that logic into `TradeActor`.

## Problem Statement
- **Logic Fragmentation:** The "how" (calculation) is in the Executor, while the "what" (state) is in the Actor.
- **Testing Overhead:** Testing trailing logic requires mocking the entire `TradeExecutor` ecosystem.
- **Broker Coupling:** Trading rules are tied to the execution service.

## Proposed Solution
Enhance `TradeActor` to hold the trade's configuration (stop loss rules, ATR) and expose a method `on_price_update(price)`. This method will return any necessary actions (like `ModifyStopLoss`) based on its internal state and rules.

## Key Requirements
- `TradeActor` must be initialized with strategy parameters (e.g., `breakeven_r`, `trail_distance`).
- `TradeActor.handle_event(TradeEvent.PRICE_UPDATED)` should check for rule violations or improvements.
- `TradeExecutor` should become a "dumb" coordinator that passes price updates to the actor and executes the actor's requested modifications.

## Success Criteria
- Trailing stop and breakeven logic are removed from `executor.py`.
- New unit tests in `tests/domain/test_trade_actor_logic.py` prove the logic works for BUY/SELL across multiple price ticks.
- Zero regression in existing trade management behavior.

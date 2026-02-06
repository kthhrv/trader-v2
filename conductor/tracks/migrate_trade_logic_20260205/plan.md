# Implementation Plan: Migrate Active Trade Logic to TradeActor

## Phase 1: Enhanced TradeActor [checkpoint: 36ee454]
Equip the `TradeActor` with the parameters and logic needed to make decisions.

- [x] Task: Update `TradeActor` to store configuration (entry, ATR, stop/trailing rules). [7820c13]
- [x] Task: Implement `TradeActor` logic to detect breakeven and trailing stop triggers. [375222e]
    - [x] Write unit tests for BE trigger inside `TradeActor`.
    - [x] Write unit tests for Trailing Stop calculation inside `TradeActor`.
    - [x] Implement the logic within the `TradeActor` class.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Enhanced TradeActor' (Protocol in workflow.md)

## Phase 2: Refactor Executor [checkpoint: fe1bc6a]
Simplify the `TradeExecutor` by delegating logic to the `TradeActor`.

- [x] Task: Modify `TradeExecutor._monitor_position` to pass price updates and act on `TradeActor` commands. [b005217]
    - [x] Write tests showing `TradeExecutor` responding to an actor's "request to modify" signal.
    - [x] Remove procedural BE/Trailing logic from `executor.py`.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Refactor Executor' (Protocol in workflow.md)

## Phase 3: Final Verification
Ensure the end-to-end flow is robust and better tested.

- [x] Task: Run full suite of E2E tests to ensure no regressions. [b005217]
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Final Verification' (Protocol in workflow.md)
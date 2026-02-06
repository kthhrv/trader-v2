# Implementation Plan: Migrate Active Trade Logic to TradeActor

## Phase 1: Enhanced TradeActor [checkpoint: 36ee454]
Equip the `TradeActor` with the parameters and logic needed to make decisions.

- [x] Task: Update `TradeActor` to store configuration (entry, ATR, stop/trailing rules). [7820c13]
- [x] Task: Implement `TradeActor` logic to detect breakeven and trailing stop triggers. [375222e]
    - [ ] Write unit tests for BE trigger inside `TradeActor`.
    - [ ] Write unit tests for Trailing Stop calculation inside `TradeActor`.
    - [ ] Implement the logic within the `TradeActor` class.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Enhanced TradeActor' (Protocol in workflow.md)

## Phase 2: Refactor Executor
Simplify the `TradeExecutor` by delegating logic to the `TradeActor`.

- [x] Task: Modify `TradeExecutor._monitor_position` to pass price updates and act on `TradeActor` commands. [b005217]
    - [ ] Write tests showing `TradeExecutor` responding to an actor's "request to modify" signal.
    - [ ] Remove procedural BE/Trailing logic from `executor.py`.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Refactor Executor' (Protocol in workflow.md)

## Phase 3: Final Verification
Ensure the end-to-end flow is robust and better tested.

- [ ] Task: Run full suite of E2E tests to ensure no regressions.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Final Verification' (Protocol in workflow.md)

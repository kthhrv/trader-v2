# Implementation Plan: FSM TradeActor Refactor

## Phase 1: Foundation & Core FSM [checkpoint: bc26ac9]
Define the `TradeActor` structure and core state machine logic.

- [x] Task: Define `TradeActor` states and events in `app/domain/models.py` or a new `app/domain/trade_actor.py`. [9556e68]
- [x] Task: Create `TradeActor` base class with state transition logic. [907c034]
    - [ ] Write unit tests for basic state transitions (`PENDING` -> `OPEN`).
    - [ ] Implement `TradeActor` core logic to pass tests.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Foundation & Core FSM' (Protocol in workflow.md)

## Phase 2: Integration with Execution & Persistence [checkpoint: 0f7be2a]
Connect the `TradeActor` to the database and existing execution adapters.

- [x] Task: Implement state persistence and recovery for `TradeActor`. [8f3a489]
    - [ ] Write tests for saving/loading `TradeActor` state from DB.
    - [ ] Implement persistence logic in `app/database/queries.py` and `TradeActor`.
- [x] Task: Integrate `TradeActor` with `IGClient` (or `executor.py`). [70eaa46]
    - [ ] Write integration tests for order execution driven by `TradeActor`.
    - [ ] Implement adapter integration logic.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Integration with Execution & Persistence' (Protocol in workflow.md)

## Phase 3: Active Trade Management
Implement dynamic updates like trailing stops and manual overrides.

- [x] Task: Implement dynamic stop-loss updates in `TradeActor`. [4923ac3]
    - [ ] Write tests for `OPEN` -> `MODIFYING` -> `OPEN` transition for SL updates.
    - [ ] Implement logic to handle price updates and trigger SL modifications.
- [x] Task: Refactor `trader.py` or `executor.py` to use `TradeActor` for all trades. [8fd4e23]
    - [ ] Write E2E tests for the new flow.
    - [ ] Perform the final refactoring.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Active Trade Management' (Protocol in workflow.md)

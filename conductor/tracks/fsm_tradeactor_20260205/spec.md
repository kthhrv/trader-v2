# Specification: FSM TradeActor Refactor

## Overview
The current trade execution logic is likely procedural or spread across multiple services (`executor.py`, `trader.py`). This track aims to centralize trade lifecycle management into a Finite State Machine (FSM) implemented as a `TradeActor`. This will enable "Active Trade Management," allowing the system to handle complex state transitions (e.g., partial fills, dynamic trailing stop updates, manual overrides) in a robust and testable manner.

## Problem Statement
- **Tight Coupling:** Trade logic is intertwined with execution and risk management.
- **Limited Maneuverability:** Difficult to update a trade's parameters (like stops) once it's in progress.
- **Testing Complexity:** Hard to simulate specific trade lifecycle scenarios (e.g., what happens if a stop-loss is triggered while the market is closed).

## Proposed Solution
Introduce a `TradeActor` class that uses a state machine to manage the lifecycle of a single trade.
States might include:
- `PENDING`: Order sent but not yet acknowledged.
- `OPEN`: Trade is active and being managed.
- `MODIFYING`: A change (e.g., stop-loss update) is in flight.
- `CLOSING`: Close order sent.
- `CLOSED`: Terminal state.

## Key Requirements
- **State Persistence:** The `TradeActor` state must be recoverable from the database.
- **Deterministic Transitions:** State changes must be driven by explicit events (e.g., `OrderAcknowledged`, `PriceUpdated`, `ManualCloseRequested`).
- **Isolation:** Each trade is managed by its own `TradeActor` instance.
- **Testability:** State transitions must be testable without requiring a live market connection or complex service mocks.

## Success Criteria
- Existing trade execution flow is replaced by the `TradeActor`.
- 100% unit test coverage for `TradeActor` state transitions.
- Successful E2E test showing a trade being opened, modified (active management), and closed.

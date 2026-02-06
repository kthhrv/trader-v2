# Implementation Plan: Optimize TradeActor History

## Phase 1: Filter Events
Modify the `TradeActor` to filter out high-frequency events from history.

- [~] Task: Update `TradeActor.handle_event` to skip appending `PRICE_UPDATED` to history.
    - [ ] Write unit test ensuring `PRICE_UPDATED` is not recorded.
    - [ ] Implement the filter.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Filter Events' (Protocol in workflow.md)

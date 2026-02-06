# Implementation Plan: Configurable Sentinel Trigger Mode

## Phase 1: Configuration & Settings [checkpoint: c3a7c3c]
Add the new configuration parameter to the system.

- [x] Task: Define `SENTINEL_MODE` in `app/core/config.py`.
    - [ ] Add `SENTINEL_MODE` to the `Settings` class with a default value of `"MONITOR_ONLY"`.
- [x] Task: Update `.env.example` to include the new variable.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Configuration & Settings' (Protocol in workflow.md)

## Phase 2: Logic Implementation
Update the Sentinel to respect the new configuration.

- [ ] Task: Implement mode-aware triggering in `app/services/watcher.py`.
    - [ ] Write unit tests for `MetricSensor._trigger_bot` to verify it skips Redis publishing when in `MONITOR_ONLY` mode.
    - [ ] Write unit tests for `MetricSensor._trigger_bot` to verify it publishes to Redis when in `AUTO_TRADE` mode.
    - [ ] Update `MetricSensor._trigger_bot` implementation to check `settings.SENTINEL_MODE`.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Logic Implementation' (Protocol in workflow.md)

## Phase 3: Final Verification
Ensure the system behaves correctly with different environment settings.

- [ ] Task: Manual E2E test of Sentinel behavior.
    - [ ] Set `SENTINEL_MODE=MONITOR_ONLY` in `.env` and verify no strategy runs are triggered on technical spikes.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Final Verification' (Protocol in workflow.md)

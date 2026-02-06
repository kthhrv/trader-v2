# Specification: Configurable Sentinel Trigger Mode

## Overview
The Sentinel currently automatically triggers a strategy run (`RUN_STRATEGY`) whenever a technical trigger (RVOL, Parabolic) is detected. This feature makes that behavior configurable via an environment variable, allowing the system to operate in a "Monitor Only" mode where it alerts the user without initiating automated analysis.

## Problem Statement
Automated triggers can be noisy or consume unnecessary Gemini API tokens during volatile periods. Users need a way to disable the automated execution while still receiving the underlying technical alerts.

## Functional Requirements
- **Configuration:** Add a new environment variable `SENTINEL_MODE` to `app/core/config.py`.
- **Modes:**
    - `MONITOR_ONLY` (Default): Sentinel detects triggers and sends notifications, but DOES NOT publish to the `trade_commands` Redis channel.
    - `AUTO_TRADE`: Sentinel behaves as it does currently (notifies and triggers strategy).
- **Logic:** Update `MetricSensor._trigger_bot` in `app/services/watcher.py` to check the configured mode before publishing the Redis command.
- **Persistence:** Ensure the setting is reflected in the system's runtime configuration.

## Non-Functional Requirements
- **Default Safety:** The system must default to `MONITOR_ONLY` if the variable is missing to prevent unintended trade initiations.

## Acceptance Criteria
- When `SENTINEL_MODE=MONITOR_ONLY`, a technical trigger results in a Home Assistant notification but NO `RUN_STRATEGY` log or action.
- When `SENTINEL_MODE=AUTO_TRADE`, a technical trigger results in both a notification and a published `RUN_STRATEGY` command.
- The default behavior (no `.env` entry) is `MONITOR_ONLY`.

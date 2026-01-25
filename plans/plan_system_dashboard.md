# Plan: System Status Dashboard (Reflex UI)

**Objective:** Add a "System" tab to the Trader V2 Dashboard to visualize the health and metrics of the distributed microservices architecture.

## 1. Data Source: Redis "System Bus"
We will use Redis as the source of truth for monitoring. Services will publish "Heartbeats" to a dedicated channel or update keys with TTL.

- **Keys:**
    - `system:status:streamer` -> `{"state": "UP", "markets": 6, "last_tick": "timestamp"}`
    - `system:status:watcher` -> `{"state": "UP", "last_scan": "timestamp"}`
    - `system:status:trader` -> `{"state": "IDLE", "last_run": "timestamp"}`

## 2. Service Updates
- **`market-streamer`:** Update `manager.py` to write its status to Redis every 10s.
- **`watcher`:** Update to write status.
- **`trader`:** Update `CommandListener` to write status.

## 3. UI Implementation (Reflex)
Create `dashboard/pages/system.py`.

### Components:
1.  **Service Grid:**
    - Cards for Infra, App, Watchdog.
    - Green/Red indicators based on "Last Heartbeat" (if > 30s ago, show RED).
2.  **Latency Monitor:**
    - Show "Time since last tick" for each market (FTSE, SPX, etc).
3.  **Logs Viewer (Optional):**
    - Tail logs? (Hard via Redis, maybe skip for V1).
4.  **Control Panel:**
    - Buttons to `RUN_STRATEGY` manually via Redis Command (bypassing CLI).

## Implementation Steps

### Phase 1: The Heartbeat
1.  Create `app/core/monitor.py`: A helper class `SystemMonitor`.
2.  Integrate `SystemMonitor.heartbeat("service_name", data)` into all 3 main services.

### Phase 2: The UI
3.  Add `redis` dependency to Dashboard.
4.  Create the "System" page layout in Reflex.
5.  Implement a `State` class that polls Redis keys for updates.

## Success Criteria
- Opening the UI shows "Streamer: ONLINE (Last tick 2s ago)".
- Stopping a container turns the indicator RED within 30 seconds.

# Plan: Centralized Command Listener (COMPLETED)

**Status: IMPLEMENTED**
- `CommandListener` is live in `app/services/command_listener.py`.
- `main.py` runs in `--server` mode.
- Watcher triggers commands via Redis.

## Architecture Change

**Objective:** Transition the `trader` container from a passive Scheduler/One-off script into a persistent **Execution Server** that listens for trading commands via Redis. This centralizes execution logic, solving concurrency issues and simplifying the architecture.

## Architecture Change

### 1. The `CommandBus` (Redis Channel: `trade_commands`)
A new communication channel for control messages.
- **Protocol:** JSON `{"command": "RUN_STRATEGY", "market": "ftse", "reason": "spike_detected"}`

### 2. The `TraderServer` (New Role for `trader`)
Instead of running `apscheduler` directly in `main.py`, the `trader` container will run a `CommandListener` service.
- **Responsibilities:**
    - Listens to `trade_commands` channel.
    - Manages a `LockManager` (to prevent double-trading the same market).
    - Executes `StrategyEngine`.
    - **Also runs the Scheduler** (as an internal background task that *publishes* commands to itself).

### 3. The `Watcher` (Trigger)
- **Role:** Pure Sensor.
- **Action:** When spike detected -> `redis.publish("trade_commands", ...)`
- **Benefit:** Watcher doesn't need to load the heavy AI libraries or DB logic. It just stays lightweight.

---

## Implementation Steps

### Phase 1: The Command Listener
1.  Create `app/services/command_listener.py`.
2.  Implement `listen()` loop (Redis Subscriber).
3.  Implement `handle_command(payload)`:
    - Check Lock.
    - Run Strategy.

### Phase 2: Refactor `main.py`
4.  Update `main.py` to support a `--server` mode (or replace `--scheduler`).
5.  In `--server` mode:
    - Start `CommandListener`.
    - Start `Scheduler` (but modify scheduler to PUBLISH commands instead of running them).

### Phase 3: Update Watcher
6.  Modify `PriceSensor` in `app/services/watcher.py`.
7.  Instead of `send_notification`, it should `redis.publish("trade_commands")`.

### Phase 4: Verification
8.  Use `inject_spike.py` to trigger the Watcher.
9.  Verify `Watcher` publishes -> `Trader` receives -> `Trader` executes.

## Success Criteria
- Watcher container becomes lightweight (no AI/Strategy deps loaded).
- Trader container becomes the single point of truth for execution.
- Scheduler and Watcher can both trigger trades safely.

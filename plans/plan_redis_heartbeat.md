# Plan: Migrate Watchdog Heartbeat to Redis

**Objective:** Replace the shared file-based heartbeat (`data/heartbeat.txt`) with a Redis key-based mechanism for the main App/Scheduler.

## Why?
- **Decoupling:** Removes the need for a shared volume mount (`HOST_DATA_PATH`) between `trader` and `watchdog`.
- **Reliability:** Leverages existing Redis infrastructure.

---

## Architecture Changes

### 1. Heartbeat Writer (`app/cli/schedule.py`)
- **Current:** Writes timestamp to `data/heartbeat.txt`.
- **New:** Writes timestamp to Redis key `health:app:last_seen`.
- **Frequency:** Every 1 minute.

### 2. Heartbeat Reader (`watchdog.py`)
- **Current:** Reads `data/heartbeat.txt`.
- **New:** Reads Redis key `health:app:last_seen`.
- **Logic:**
    - Connect to Redis.
    - Check `health:app:last_seen`. If missing or stale (> 5m) -> **Alert**.

### 3. Docker Compose (`docker-compose.*.yml`)
- **Action:** Re-evaluate volume mounts in future (shared logs may still need them).

---

## Implementation Steps

### Phase 1: Code Update
1. [ ] Update `app/cli/schedule.py`:
    - Use `redis.asyncio` to write `health:app:last_seen`.
2. [ ] Update `watchdog.py`:
    - Add `redis` client.
    - Update `check_liveness()` to fetch from Redis.

### Phase 2: Configuration
3. [ ] Ensure `REDIS_HOST` is available to the `watchdog` container.

## Verification
- Stop `trader` container. Verify `watchdog` alerts after 5 minutes.
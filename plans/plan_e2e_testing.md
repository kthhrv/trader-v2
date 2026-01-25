# Plan: End-to-End (E2E) Testing Strategy

**Objective:** Validate the integrity of the full 3-stack Microservices architecture (`infra`, `app`, `watchdog`). We need a reproducible test suite that verifies the "Event Loop" from Data Ingestion -> Publishing -> Detection -> Execution -> Persistence.

## Scope of Testing

### 1. The "Nervous System" Test (Redis & Streamer)
- **Goal:** Prove `market-streamer` is alive and publishing ticks.
- **Method:** Subscribe to `market_data`. Assert tick frequency > 0.
- **Validation:** Redis message receipt.

### 2. The "Recorder" Test (Candle Aggregation)
- **Goal:** Prove `market-streamer` is writing to SQLite.
- **Method:** Inject 60s of synthetic ticks. Wait 65s.
- **Validation:** Query `historical_candles`. Assert `resolution='1Min'` row exists for the test epic.

### 3. The "Reflex" Test (Watcher -> Trader)
- **Goal:** Prove a volatility spike triggers a strategy run.
- **Method:**
    1. Inject "Spike" ticks (e.g., +0.5% jump).
    2. Monitor `trade_commands` channel.
    3. Monitor `trader-v2` logs (or DB `trade_signals`).
- **Validation:** `TradeSignal` created in DB with `reason` matching the spike.

### 4. The "Watchdog" Test (Health Check)
- **Goal:** Prove the watchdog alerts on stale data.
- **Method:** Stop `market-streamer`. Wait.
- **Validation:** Watchdog logs error or sends alert.

---

## Implementation Roadmap

### Phase 1: The Test Runner (`tests/e2e/runner.py`)
A standalone Python script (running on the host or a temp container) that orchestrates the tests.
- Uses `redis-py` to inject/listen.
- Uses `sqlalchemy` to check DB state.
- Uses `docker` SDK (optional) to check container health.

### Phase 2: Test Scenarios
1.  **`test_data_flow_latency`**: Measure time from Injection -> Subscriber Receipt.
2.  **`test_regime_switching`**: Inject "Choppy" data (low volatility). Verify Strategy Log says "Mean Reversion".
3.  **`test_persistence`**: Verify WAL mode handles concurrent writes during high load.

### Phase 3: CI/CD Integration
- Add `inv test:e2e` to `tasks.py`.
- Ensure it spins up a fresh "Test Environment" (using `docker-compose.test.yml`?) or reuses the Dev environment.

## Success Criteria
- Running `inv test:e2e` provides a Pass/Fail report for the entire distributed system.
- We can confidently deploy changes knowing the "Event Loop" is unbroken.

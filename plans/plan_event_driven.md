# Plan: Event-Driven Triggers & Watchers (COMPLETED)

**Status: IMPLEMENTED in v2.0.0**
- `WatcherService` and `PriceSensor` are live.
- Integrated with Redis Command Bus.

## 1. The Watcher Architecture

Since we already have `trader-infra` publishing ticks to Redis, we can add **Sensors** to the `trader-app` stack.

### Components
- **`PriceSensor`:** A persistent background task that monitors the Redis `market_data` channel for all Epics. It calculates "Velocity" and "Volatility Spikes."
- **`MacroSensor`:** A polling task that checks an Economic Calendar API (e.g., Finnhub) and schedules "Wake Up" events for the bot based on high-impact releases (Fed, CPI).
- **`SocialSensor` (Optional/Future):** A listener for high-impact social media events (Trump/Musk).

## 2. Trigger Logic

### A. Volatility Spike (PriceSensor)
- **Detection:** Uses a 60-second sliding window of Redis ticks.
- **Formula:** `(Current_Price - Price_60s_ago) / Price_60s_ago > Threshold`.
- **Action:** If threshold (e.g., 0.15%) is crossed, fire `VolatilityTriggerEvent`.

### B. Economic Calendar (MacroSensor)
- **Detection:** Polls Finnhub once per morning for "High Impact" events.
- **Action:** Schedules an internal timer to trigger `StrategyEngine.run_strategy()` exactly at the release time (e.g., 13:30:00).

## 3. Integration with Strategy Engine

We need a way for the Watcher to "Wake Up" the bot.
- **The Reflex:** A new method `watcher.process_event()`.
- **Response:**
    - `VolatilityTriggerEvent` -> Calls `engine.run_strategy()` with `dry_run=False` and `strategy_id=momentum_breakout`.
    - `NewsTriggerEvent` -> Calls `engine.run_strategy()` with `strategy_id=us_volatility`.

## 4. Implementation Steps

### Phase 1: Infrastructure (COMPLETED)
1. [x] Create `app/services/watcher.py`.
2. [x] Implement a base `WatcherService` that manages multiple async sensor tasks.
3. [x] Update `main.py` to support a new `--watch` command.

### Phase 2: The Price Sensor (COMPLETED)
4. [x] Implement `PriceSensor` listening to Redis `market_data`.
5. [x] Add "Detection Logic" with configurable thresholds per market.
6. [x] Wire it to send a Home Assistant notification when a spike is detected.

### Phase 3: The Macro Sensor (The Schedule Optimizer)
7. Integrate Finnhub API for Economic Calendar data.
8. Implement a scheduler that "Pre-Wakes" the bot 30 seconds before a major event.

### Phase 4: Full Automation (The "Hands-Off" Bot)
9. Enable the Watcher to trigger full strategy runs.
10. Implement "Cooldowns" (e.g., "Don't trigger twice for the same move").

## Success Criteria
- Bot identifies a >0.1% move in FTSE/SPX and sends an HA notification within 2 seconds.
- Bot automatically wakes up for a US CPI release without manual scheduling.
- The 24/7 data recording (market-streamer) remains uninterrupted throughout.

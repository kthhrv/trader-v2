# Plan: Event-Driven Trigger Logic (V3)

## Objective
Move the system from "Polling" (checking every 5 mins) to "Event Driven" (reacting to market structure). We need a "Silent Sentinel" that monitors real-time data using cheap mathematical logic and only wakes up the expensive AI (Senior Analyst) when a significant trading opportunity is detected.

## 1. The "Silent Sentinel" Component [DONE]
**Role:** A lightweight service (integrated into `WatcherService` or `Streamer`) that calculates V3 metrics on every **1-minute** candle close.
**Implementation:** Created `MetricSensor` class in `app/services/watcher.py`.
**Inputs:** Real-time 1m candles from Redis (`market_candles` channel).

## 2. Trigger Conditions (The "Escalation Matrix") [DONE]
Implemented in `MetricSensor.on_candle`:

### A. Volatility Events
- [x] **RVOL Spike:** `Current_Vol > 2.0 * Avg_Vol`.

### B. Structural Events
- [x] **Parabolic State:** `(Price - EMA20) > 2.5 * ATR`.

*(Note: Session Break and EMA Cross triggers deferred to V3.1)*

## 3. The Workflow [DONE]
1.  [x] **Streamer:** Publishes `candle_closed` event to Redis. (Updated `CandleBuilder`).
2.  [x] **Sentinel:** Consumes event, runs `TechnicalAnalysis` (Math).
3.  [x] **Logic:** Checks if any Trigger Condition is met.
4.  [x] **Action:** Publish `trigger_analysis` event to Redis (mapped to `RUN_STRATEGY`).
5.  [x] **CommandListener:** Consumes `RUN_STRATEGY`, wakes up `StrategyEngine`, runs AI.

## 4. Implementation Steps
1.  [x] **Enhance `WatcherService`:** Added `MetricSensor`.
2.  [x] **Define Event Bus:** Used `market_candles` for data and `trade_commands` for actions.
3.  [x] **Update `CommandListener`:** Verified `RUN_STRATEGY` handling.

## 5. Benefits
- **Token Efficiency:** We stop asking the AI "Is there a trade?" when the market is flat.
- **Responsiveness:** We react instantly to a breakout.
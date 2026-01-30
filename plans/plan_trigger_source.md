# Feature: Trigger Source Tracking

**Status:** Completed (2026-01-30)
**PR:** `feat(telemetry): implement trigger source tracking and add analysis tool`

## Problem
Previously, the database stored trade signals but didn't record **why** a trade was initiated (e.g., Scheduled Open vs. Sentinel RVOL Spike). This made it impossible to analyze the performance of the Sentinel (V3 logic) versus standard scheduled strategies.

## Solution Implemented
Added a `trigger_source` column to the `trade_signals` table and wired all trigger points (Sentinel, Scheduler, Manual) to populate it.

### 1. Database Model
- `TradeSignal` model now includes `trigger_source: str` (Default: "unknown").

### 2. Service Layer Plumbing
- **`app/services/trader.py`**: Accepts `trigger_source` in `run_strategy` and persists it.
- **`app/services/command_listener.py`**: Extracts `reason` from Redis payload (e.g., `sentinel_PARABOLIC_EXT_2.9x`).
- **`app/cli/schedule.py`**: Passes `"scheduler"` as the source.
- **`app/cli/trade.py`**: Passes `"manual"` for CLI tests.

### 3. Migration
Manual SQL migration executed on Live and Demo environments:
```sql
ALTER TABLE trade_signals ADD COLUMN trigger_source VARCHAR DEFAULT 'unknown';
```

### 4. Tooling
Created `scripts/analyze_trades.py` to easily inspect trade history and sources.
**Usage:**
```bash
python3 scripts/analyze_trades.py --env demo --limit 10
```

## Future Analytics
We can now run queries to compare performance:
```sql
SELECT trigger_source, COUNT(*), AVG(pnl) 
FROM trade_signals s 
JOIN trade_executions e ON s.id = e.signal_id 
GROUP BY trigger_source;
```
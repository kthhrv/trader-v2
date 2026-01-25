# Technical Debt & Code Cleanup

This document tracks identified areas where the codebase deviates from best practices, contains duplication, or requires refactoring for maintainability.

---

## 1. Configuration & Timezones

### ⚠️ Market Hours Duplication
- **Location:** `app/services/market_status.py` vs `app/core/markets.py`
- **Issue:** 
    - `market_status.py` has a method `_get_market_hours` with hardcoded open/close times and timezones for various countries.
    - `markets.py` defines `MARKET_CONFIGS` with `schedule` (open time) and `timezone`.
    - **Risk:** These two sources of truth can drift apart. Currently, `market_status` uses `Europe/Berlin` for DAX while `markets` uses `Europe/London`.
- **Remediation:** Refactor `MarketStatusService` to inject `MARKET_CONFIGS` and derive open/close times dynamically from the centralized config.

### ⚠️ "Pre-Market" Logic Flaw in Analyzer
- **Location:** `app/services/analyzer.py` -> `_determine_strategy`
- **Issue:** The `time_since_open` calculation compares `now` to `market_open` (derived from today's date + schedule time). It does not check if "today" is actually a trading day (e.g., it runs on Sunday).
- **Mitigation:** Currently mitigated by `TraderEngine` checking `is_holiday` before calling the analyzer, and the Scheduler handling day-of-week logic.
- **Remediation:** Pass the `MarketStatus` object into `Analyzer` to validate market state before calculating time deltas.

---

## 2. Security

### ⚠️ Session Token Exposure (Streamer)
- **Location:** `app/services/streamer.py` and `ps aux`
- **Issue:** The `CST` and `XST` tokens are passed as command-line arguments to the `market-streamer` Node.js process. This makes them visible to any user on the host machine running `ps aux`.
- **Remediation:** Refactor the Node.js spawner to pass tokens via Environment Variables (`env={...}`) or via a secured IPC channel (stdin).

---

## 3. Database

### ⚠️ SQLite "Wal Checkpoint" Logic
- **Location:** `app/database/session.py`
- **Issue:** We manually run `PRAGMA wal_checkpoint(TRUNCATE)` on startup.
- **Risk:** This might lock the DB if another process (Streamer) is writing.
- **Remediation:** Remove manual checkpoints once migrated to PostgreSQL.

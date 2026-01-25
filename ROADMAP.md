# Trader V2 Roadmap

**Current Version:** 2.0.0 (The Microservices Release)
**Status:** Production Live (Demo Account) on `192.168.0.191`.

## Q1 2026 Priorities

### 1. Visibility & Observability (Reflex UI)
- [ ] **System Status Tab:** Implement `plan_system_dashboard.md`.
    - Real-time Redis heartbeats from all 4 stacks.
    - Latency monitoring (time since last tick per market).
- [ ] **Market Data Explorer:** Implement `plan_market_explorer.md`.
    - Candlestick charts for the local SQLite database.
    - Verify 24/7 recording integrity.

### 2. Operational Safety (The "Shield")
- [ ] **Global Trading Pause (Kill Switch):**
    - Implement a Redis-backed flag `PAUSE_TRADING`.
    - Add a "Panic Button" to the UI.
    - All services (Trader, Watcher) check this flag before execution.
- [ ] **Remote Control Chat Bot:**
    - Integrate Telegram or Discord adapter.
    - Command: `/status` (Current account health).
    - Command: `/pause` (Activate Kill Switch).
    - Command: `/closeall` (Emergency exit of all positions).

### 3. Intelligence & Reflexes (The "Sharpness")
- [ ] **Macro Sensor:**
    - Integrate Finnhub API for Economic Calendar.
    - Trigger "Pre-Event" strategy runs for high-impact releases (CPI, Fed).
- [ ] **Social Sensor:**
    - (Future) Monitor X/Twitter/News sources for high-velocity sentiment shifts.

### 4. Stability & Scale (The "Foundation")
- [ ] **Database Migration:** Implement `plan_db_migration.md`.
    - Move from SQLite to external PostgreSQL (TimescaleDB).
    - Decouple stacks from filesystem volume dependencies.
- [ ] **Automated E2E Suite:** Implement `plan_e2e_testing.md`.
    - Reproducible test runner for the full asynchronous event loop.

## Backlog / Future Tech Debt
- **Paper Trading Mode:** Explicit support for IG's Paper Trading API.
- **Multi-Account Support:** Simultaneous trading of Demo and Live accounts.
- **Session Hardening:** Refactor streamer to pass CST/XST tokens via Environment Variables (Security fix).
- **ML Parameter Tuning:** Use historical recording data to optimize ADX thresholds and stop distances.
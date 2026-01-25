# Technical Gaps & Execution Risks

This document tracks known "holes" where the current system implementation may fail to perfectly action the intent described in `TRADING.md`.

---

## 1. Execution Gaps

### 🕳️ "Market if Touched" vs. True Limit Orders
- **Description:** The bot currently uses local async loops (`_wait_for_trigger`) to monitor prices. Once a target is hit, it fires a `MARKET` order.
- **Risk:** In high-volatility environments (especially Mean Reversion pullbacks), price can touch a level and bounce instantly. By the time the `MARKET` order reaches IG, the price may have moved significantly against us (Slippage).
- **Proposed Fix:** Support `order_type="LIMIT"` or `STOP` in `ig_client.create_order` to place orders on the exchange's book.

### 🕳️ Spread Race Condition
- **Description:** The spread is checked milliseconds before firing an order. 
- **Risk:** Spread can widen significantly (e.g., from 1.0 to 15.0) during a news spike in the 200ms it takes for the API call to travel. The trade will fill at a toxic price despite the pre-check.
- **Proposed Fix:** Use IG's `trailingStop` or `guaranteedStop` at creation, and implement a maximum slippage tolerance (offset) in the order call.

---

## 2. Resilience Gaps

### 🕳️ Stateless Monitoring (The "Orphan" Risk)
- **Description:** Position monitoring (`_monitor_position`) is an in-memory `async` loop. 
- **Risk:** If the `trader-v2` container restarts (redeploy, Docker update, OOM crash) while a position is open, the loop dies. The position remains open on IG but is no longer managed by the bot. It will not be trailed or force-closed at market end.
- **Proposed Fix:** Implement a "Recovery Service" that queries IG Open Positions on startup and re-attaches monitor loops to any discovered "Orphan" trades.

### 🕳️ Deal ID Handshake Failure
- **Description:** The system relies on a 5-second polling loop to resolve a `dealReference` into a `dealId`.
- **Risk:** If the bot crashes or the network blips during this handshake, the trade is live on IG but the local DB and Monitor will never know the `dealId`.
- **Proposed Fix:** Write the `dealReference` to a "Pending Handshake" table in SQLite immediately after creation so it can be resolved after a restart.

---

## 3. Data & Scale Gaps

### 🕳️ SQLite Write Concurrency
- **Description:** While WAL mode is enabled, SQLite still has limitations with multiple writers across different containers/processes.
- **Risk:** During a massive multi-market volatility event (e.g., US Open), the Streamer (writing candles) and Trader (writing signals) might clash, leading to "Database is locked" errors and lost data.
- **Proposed Fix:** Migrate to external PostgreSQL as per `plan_db_migration.md`.

### 🕳️ Clock Drift
- **Description:** The system relies on the host OS clock for scheduling and candle building.
- **Risk:** If the Debian server's clock drifts by even 10 seconds, the "Market Open" 30-minute bypass logic and candle alignment will be inaccurate compared to IG's server time.
- **Proposed Fix:** Sync system time with NTP and log the offset between local time and IG server time (provided in API headers).

---

## 4. Safety Gaps

### 🕳️ Lack of a "Circuit Breaker"
- **Description:** There is no logic to stop trading if the account experiences a "Maximum Daily Drawdown."
- **Risk:** A strategy bug or runaway "Reflex" loop could repeatedly enter losing trades, draining the account.
- **Proposed Fix:** Implement a `DailyRiskManager` that checks total realized P&L and disables the `CommandBus` if a loss limit is reached.

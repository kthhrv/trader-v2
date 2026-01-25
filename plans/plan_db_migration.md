# Plan: Database Migration (SQLite -> External PostgreSQL/TimescaleDB)

**Objective:** Migrate the data layer from local SQLite files to an external, network-accessible PostgreSQL/TimescaleDB server. This eliminates volume sharing complexity and provides a more robust data backend.

## Why Migrate to External Postgres?
1.  **Deployment Simplification:** Stacks no longer need to share a common filesystem volume for data. Connectivity is purely network-based.
2.  **Concurrency:** Native support for multiple concurrent writers (Streamer, Trader, Watcher).
3.  **Scalability:** High-frequency time-series data is better managed by TimescaleDB's partitioning (Hypertables).

---

## Architecture Changes

### 1. External Database
- **Host:** `192.168.0.191` (or local host IP reachable from containers).
- **Service:** PostgreSQL with TimescaleDB extension installed.

### 2. Config Update
- **`app/core/config.py`:** Add fields for `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`.
- **`DATABASE_URL`:** Transition to `postgresql+asyncpg://user:pass@host:port/db`.

---

## Implementation Steps

### Phase 1: Preparation & Dependencies
1. [ ] Create the database and user on the external Postgres server.
2. [ ] Add `asyncpg` and `psycopg2-binary` to the project dependencies.
3. [ ] Update `app/core/config.py` with the new database settings.

### Phase 2: Code Refactor
4. [ ] Update `app/database/session.py`:
    - Switch from `sqlite+aiosqlite` to `postgresql+asyncpg`.
    - Remove SQLite-specific logic (WAL pragmas).
5. [ ] Update `init_db()` to support Postgres schema initialization.

### Phase 3: Data Migration (Optional)
6. [ ] Create a script to migrate existing `trade_signals` and `trade_executions` from SQLite to Postgres.
7. [ ] *Note:* Historical candles can be rebuilt by the 24/7 streamer if history is not critical.

### Phase 4: TimescaleDB Optimization
8. [ ] Execute SQL to convert `historical_candles` into a **Hypertable** for optimal performance.

## Success Criteria
- Bot successfully connects to the external Postgres database from all containers.
- `trader-v2` and `trader-streamer` containers can run on separate stacks/hosts without sharing volumes.
- Logs show successful database initialization and table creation on the new backend.
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
1. [x] **Production:** Create a dedicated user (`trader`) and database (`trader2`) on the external Postgres server.
2. [x] **Local Dev:** Update `docker/docker-compose.infra.dev.yml` to include a `timescale/timescaledb:latest-pg18` container.
3. [x] Add `asyncpg` and `psycopg2-binary` to the project dependencies.
4. [x] Update `app/core/config.py` with the new database settings (`POSTGRES_USER`, `POSTGRES_HOST`, etc.).
5. [x] **WAIT FOR CONFIRMATION**

### Phase 2: Code & Config Refactor
6. [x] Update `app/database/session.py`:
    - Switch from `sqlite+aiosqlite` to `postgresql+asyncpg`.
    - Remove SQLite-specific logic (WAL pragmas).
7. [x] Update `init_db()` to:
    - Support Postgres schema initialization.
    - **Execute TimescaleDB setup:** Run `SELECT create_hypertable(...)` for `historical_candles` immediately after table creation.
8. [x] Update Docker Compose files (`docker/docker-compose.*.yml`):
    - **Remove** the `HOST_DATA_PATH` volume mount (data is now over the network).
    - **Add** environment variables for Postgres connection.
9. [x] **WAIT FOR CONFIRMATION**

### Phase 3: Data Migration (Skipped)
- **Status:** Not Required for V2 Alpha.
- **Action:** System will start with an empty database. New history will be built by the streamer.
10. [x] **WAIT FOR CONFIRMATION**

### Phase 4: Verification
11. [ ] Deploy to production and verify connection.
12. [ ] Confirm `historical_candles` is a hypertable via SQL query.
13. [ ] **WAIT FOR CONFIRMATION**

## Success Criteria
- Bot successfully connects to the external Postgres database from all containers.
- `trader-v2` and `trader-streamer` containers can run on separate stacks/hosts without sharing volumes.
- Logs show successful database initialization and table creation on the new backend.

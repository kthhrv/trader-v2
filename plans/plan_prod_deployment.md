# Plan: Production Deployment (SQLite + Dockge)

**Objective:** Deploy the 3-stack microservices architecture to the remote Dockge server (`192.168.0.191`) while maintaining data persistence with SQLite. We will use absolute host paths to prevent "Split Brain" databases between stacks.

## 1. Data Strategy (The "Pragmatic" Fix)
Instead of Docker Named Volumes (which can be tricky with Dockge management), we will use **Bind Mounts** to a fixed location on the host.

- **Host Path:** `/opt/trader-v2-data`
- **Container Path:** `/app/data`
- **Result:**
    - `trader-infra` writes candles to `/opt/trader-v2-data/trader.db`.
    - `trader-app` reads signals from `/opt/trader-v2-data/trader.db`.
    - All containers share the exact same file.

## 2. Infrastructure Changes
- Update `docker-compose.infra.yml`, `docker-compose.app.yml`, and `docker-compose.watchdog.yml`.
- Change volumes from `./data:/app/data` to `${HOST_DATA_PATH:-./data}:/app/data`.
- This allows local dev to use `./data` (via default) and Prod to use `/opt/trader-v2-data` (via `.env`).

## 3. Automation (`inv deploy`)
The deployment script handles the orchestration.

- **Steps (COMPLETED):**
    1.  [x] **Build & Push:** `inv publish` pushes multi-arch images to `192.168.0.191:5000`.
    2.  [x] **Sync:** `scp` copies `docker-compose.*.yml` to the remote `/opt/stacks` directories.
    3.  [x] **Config:** Stacks are isolated by directory but linked by `HOST_DATA_PATH`.
    4.  [x] **Launch:** `inv deploy` triggers `docker compose up -d` remotely for all 3 stacks.

## Success Criteria
- Deployment runs with a single command.
- All 3 stacks on `192.168.0.191` are running.
- They all read/write to the same SQLite database file on the host.

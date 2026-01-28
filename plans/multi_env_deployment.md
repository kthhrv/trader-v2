# Multi-Environment Deployment Plan (Live + Demo)

## Objective
Enable running two fully isolated stacks of the trading system ("Live" and "Demo") on the same production server, while maintaining support for "Local" development. Each stack must have its own independent infrastructure (DB, Redis), application (Trader, UI), and observability (Grafana, Loki) components.

## Architecture

We will use Docker Compose's `project_name` feature alongside parameterized configuration to create distinct namespaces for each environment.

### Naming Convention
Containers will be named using the pattern: `<PROJECT_NAME>-<SERVICE_NAME>`
- **Live**: `live-trader`, `live-redis`, `live-grafana`
- **Demo**: `demo-trader`, `demo-redis`, `demo-grafana`
- **Local**: `local-trader`, `local-redis`, `local-grafana`

### Network Isolation
Each stack will create its own internal Docker network.
- `live_default`
- `demo_default`
- `local_default`

This ensures `live-trader` can only talk to `live-redis` and cannot accidentally pollute `demo-redis`.

### Port Mapping Strategy
To avoid host port collisions, we will parameterize external ports via `.env` files.

| Service | Local (Default) | Demo | Live |
| :--- | :--- | :--- | :--- |
| **UI (Web)** | 3000 | 3010 | 3020 |
| **UI (API)** | 8000 | 8010 | 8020 |
| **Grafana** | 3002 | 3012 | 3022 |
| **Prometheus**| 9090 | 9091 | 9092 |
| **Loki** | 3100 | 3101 | 3102 |

---

## Step 1: Refactor Docker Compose Files

We need to modify the files in `trader-v2/docker/` to remove hardcoded values.

### `docker-compose.app.yml`
- **Container Names**: Change `trader-v2` -> `${COMPOSE_PROJECT_NAME}-trader`
- **Ports**: Change `"3000:3000"` -> `"${UI_PORT:-3000}:3000"`
- **Networks**: Remove external `trader-net`. Use default network.

### `docker-compose.infra.yml`
- **Container Names**: Change `trader-redis` -> `${COMPOSE_PROJECT_NAME}-redis`
- **Networks**: Remove external `trader-net`. Use default network.

### `docker-compose.observability.yml`
- **Container Names**: Change `trader-grafana` -> `${COMPOSE_PROJECT_NAME}-grafana`
- **Ports**: Parameterize all exposed ports (`GRAFANA_PORT`, `PROMETHEUS_PORT`, `LOKI_PORT`).
- **Networks**: Remove external `trader-net`. Use default network.

### `docker-compose.watchdog.yml`
- **Container Names**: Change `trader-watchdog` -> `${COMPOSE_PROJECT_NAME}-watchdog`

---

## Step 2: Create Environment Configuration

We will create specific environment files for deployment.

### `.env.live`
```ini
COMPOSE_PROJECT_NAME=live
TRADING_ACCOUNT_ENV=LIVE
UI_PORT=3020
UI_API_PORT=8020
GRAFANA_PORT=3022
PROMETHEUS_PORT=9092
LOKI_PORT=3102
POSTGRES_DB=trader_live
```

### `.env.demo`
```ini
COMPOSE_PROJECT_NAME=demo
TRADING_ACCOUNT_ENV=DEMO
UI_PORT=3010
UI_API_PORT=8010
GRAFANA_PORT=3012
PROMETHEUS_PORT=9091
LOKI_PORT=3101
POSTGRES_DB=trader_demo
```

---

## Step 3: Update Invoke Tasks (`tasks.py`)

Instead of a bash script, we will enhance the existing `tasks.py` to handle multi-environment deployments.

### New Task Arguments
We will add an `env` argument to relevant tasks (defaulting to `local`).

```python
@task
def up(c, env="local", build=False, detach=True):
    """
    Starts the full stack for the specified environment.
    Usage: inv up --env=live
    """
    project_name = env  # e.g., 'live', 'demo'
    env_file = f".env.{env}"
    
    # Validation
    if not os.path.exists(env_file):
        print(f"Error: {env_file} not found.")
        return

    # Compose Command
    cmd = f"docker compose -p {project_name} --env-file {env_file} ..."
    # ... logic to include all yml files ...
    c.run(cmd)
```

### Config Management
The `tasks.py` will automatically look for `.env.<env>` files to inject the correct ports and variables.

---

## Step 4: Database Migration (One-Off)

We need to transition from the single `trader2` database to the dual setup.

### Procedure
1. **Stop all running traders** to release database locks.
2. **Execute SQL on Postgres Host**:

```sql
-- 1. Kill active connections to trader2
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'trader2';

-- 2. Rename existing Dev/Test DB to Demo
ALTER DATABASE trader2 RENAME TO trader_demo;

-- 3. Create fresh Live DB
CREATE DATABASE trader_live;

-- 4. Grant permissions (if needed)
-- GRANT ALL PRIVILEGES ON DATABASE trader_demo TO trader;
-- GRANT ALL PRIVILEGES ON DATABASE trader_live TO trader;
```

---

## Migration Checklist

1. [ ] **Modify YAMLs**: Update all `docker/*.yml` files with `${COMPOSE_PROJECT_NAME}` placeholders.
2. [ ] **Create Env Files**: Generate `.env.live` and `.env.demo`.
3. [ ] **Update tasks.py**: Refactor `inv up`, `inv down`, `inv logs`, `inv deploy` to accept `--env`.
4. [ ] **Database Migration**: Rename `trader2` -> `trader_demo` and create `trader_live`.
5. [ ] **Test Local**: Verify `inv up --env=local` works.
6. [ ] **Test Demo**: Deploy Demo stack to prod and verify it picks up the renamed DB.
7. [ ] **Test Live**: Deploy Live stack (fresh DB) and verify initialization.

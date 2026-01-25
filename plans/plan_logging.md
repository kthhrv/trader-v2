# Plan: Centralized Logging (COMPLETED)

**Status: IMPLEMENTED in v2.0.0**
- Loki + Promtail + Grafana stack deployed.
- `inv logs` CLI tool implemented.
- Log retention set to 90 days.

## Architecture

### 1. The Logging Stack (`trader-logging`)
A new stack defined in `docker-compose.logging.yml`.
- **Loki:** The log database. Lightweight, index-free storage.
- **Promtail:** The collector agent. It mounts `/var/lib/docker/containers` (read-only) to tail container logs directly from the host.
- **Grafana:** The visualization UI. Pre-configured with a "Trader Logs" dashboard.

### 2. Deployment
- **Prod:** Deployed as a 4th stack via `inv deploy`.
- **Local:** Deployed as part of `inv up` via `docker-compose.logging.dev.yml`.

### 3. Log Access
- **Browser:** Grafana Explorer (Query: `{compose_project=~"trader.*"}`).
- **CLI:** Use `logcli` to tail logs in the terminal, or a custom `inv logs` task that queries Loki API.

---

## Implementation Steps

### Phase 1: Configuration
1.  Create `app/core/logging/loki-config.yaml`.
2.  Create `app/core/logging/promtail-config.yaml`.
    - Configure scraping of docker containers via file path or docker socket.
    - Add pipeline stages to parse JSON logs (if applicable).

### Phase 2: Infrastructure
3.  Create `docker-compose.logging.yml`.
4.  Add `loki`, `promtail`, `grafana` services.
5.  **Critical:** Promtail must have access to docker logs on the host.

### Phase 3: Integration
6.  Update `tasks.py`:
    - `up`: Start the logging stack.
    - `deploy`: Copy logging configs and stack to remote.
7.  **Refactor Logger (`app/core/logger.py`):**
    - Configure `StreamHandler` (STDOUT) as the primary output.
    - Remove/Disable `FileHandler` when running in Docker (via ENV var) to prevent file locking and ensure Promtail can scrape the stdout stream.

### Phase 4: Verification
8.  Start stack.
9.  Open Grafana (`localhost:3000`).
10. Query `{container_name="trader-v2"}` and verify logs appear.

## Success Criteria
- A single dashboard shows interleaved logs from Streamer, Trader, and Watcher.
- Logs persist across container restarts.
- Local dev can view unified logs via Grafana or CLI.

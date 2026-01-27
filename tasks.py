from invoke import task
import time
import requests
from datetime import datetime


@task
def publish(c):
    """
    Build the Docker image and push it to the registry.
    """
    registry = "192.168.0.191:5000"
    image_name = "trader-v2"
    tag = "latest"
    full_image_name = f"{registry}/{image_name}:{tag}"

    # Get current git commit hash
    git_sha = c.run("git rev-parse HEAD", hide=True).stdout.strip()

    print(f"Building {full_image_name} (SHA: {git_sha[:7]})...")
    # We use buildx to ensure we don't have provenance issues with V1/V2 mix
    c.run(
        f"docker buildx build --build-arg GIT_COMMIT_SHA={git_sha} -t {full_image_name} --push ."
    )

    print(f"Successfully pushed {full_image_name}")


@task
def up(c):
    """
    Start the full 4-stack environment (Observability, Infra, App, Watchdog) locally.
    """
    print("--- 1. Creating Network ---")
    c.run("docker network create trader-net || true")

    print(
        "\n--- 2. Starting Observability Stack (Loki, Promtail, Grafana, Prometheus) ---"
    )
    # Removing --project-directory . to resolve relative paths from docker/ directory
    c.run(
        "docker compose -p trader-observability -f docker/docker-compose.observability.yml up -d"
    )

    print("\n--- 3. Starting Infra Stack (Redis, Streamer) ---")
    c.run(
        "docker compose --project-directory . -p trader-infra -f docker/docker-compose.infra.yml -f docker/docker-compose.infra.dev.yml up -d --build --remove-orphans"
    )

    print("\n--- 4. Starting App Stack (Trader, UI, Watcher) ---")
    c.run(
        "docker compose --project-directory . -p trader-app -f docker/docker-compose.app.yml -f docker/docker-compose.app.dev.yml up -d --build --remove-orphans"
    )

    print("\n--- 5. Starting Watchdog Stack ---")
    c.run(
        "docker compose --project-directory . -p trader-watchdog -f docker/docker-compose.watchdog.yml -f docker/docker-compose.watchdog.dev.yml up -d --build --remove-orphans"
    )

    print("\nAll stacks started. Use 'docker ps' to verify.")


@task
def down(c):
    """
    Stop and remove all 4 stacks.
    """
    print("--- 1. Stopping Watchdog Stack ---")
    c.run(
        "docker compose --project-directory . -p trader-watchdog -f docker/docker-compose.watchdog.yml -f docker/docker-compose.watchdog.dev.yml down"
    )

    print("\n--- 2. Stopping App Stack ---")
    c.run(
        "docker compose --project-directory . -p trader-app -f docker/docker-compose.app.yml -f docker/docker-compose.app.dev.yml down"
    )

    print("\n--- 3. Stopping Infra Stack ---")
    c.run(
        "docker compose --project-directory . -p trader-infra -f docker/docker-compose.infra.yml -f docker/docker-compose.infra.dev.yml down"
    )

    print("\n--- 4. Stopping Observability Stack ---")
    c.run(
        "docker compose -p trader-observability -f docker/docker-compose.observability.yml down"
    )

    print("\nAll stacks stopped.")


@task
def restart(c, stack="all"):
    """
    Restart specific stack(s): app, infra, observability, watchdog, or all.
    """
    stacks = {
        "watchdog": "docker compose --project-directory . -p trader-watchdog -f docker/docker-compose.watchdog.yml -f docker/docker-compose.watchdog.dev.yml restart",
        "app": "docker compose --project-directory . -p trader-app -f docker/docker-compose.app.yml -f docker/docker-compose.app.dev.yml restart",
        "infra": "docker compose --project-directory . -p trader-infra -f docker/docker-compose.infra.yml -f docker/docker-compose.infra.dev.yml restart",
        "observability": "docker compose -p trader-observability -f docker/docker-compose.observability.yml restart",
    }

    if stack == "all":
        for name, cmd in stacks.items():
            print(f"--- Restarting {name} ---")
            c.run(cmd)
    elif stack in stacks:
        print(f"--- Restarting {stack} ---")
        c.run(stacks[stack])
    else:
        print(
            f"Error: Unknown stack '{stack}'. Valid options: {list(stacks.keys()) + ['all']}"
        )


@task
def deploy(c, nuke=False, tag=True):
    """
    Deploy the 4 stacks to the production server (192.168.0.191).
    """
    remote_host = "192.168.0.191"
    remote_user = "root"  # Update if different
    base_path = "/opt/stacks"

    observability_path = f"{base_path}/trader-observability"
    infra_path = f"{base_path}/trader-infra"
    app_path = f"{base_path}/trader-app"
    watchdog_path = f"{base_path}/trader-watchdog"

    print(f"--- 1. Syncing Configs to {remote_host} ---")
    # Ensure directories exist
    c.run(
        f"ssh {remote_user}@{remote_host} 'mkdir -p {observability_path} {infra_path} {app_path} {watchdog_path}'"
    )

    # Sync compose files
    c.run(
        f"scp docker/docker-compose.observability.yml {remote_user}@{remote_host}:{observability_path}/compose.yaml"
    )
    c.run(
        f"scp docker/docker-compose.infra.yml {remote_user}@{remote_host}:{infra_path}/compose.yaml"
    )
    c.run(
        f"scp docker/docker-compose.app.yml {remote_user}@{remote_host}:{app_path}/compose.yaml"
    )
    c.run(
        f"scp docker/docker-compose.watchdog.yml {remote_user}@{remote_host}:{watchdog_path}/compose.yaml"
    )

    # Sync observability configs
    # The compose file expects ./observability/... relative to itself
    # We are placing compose.yaml in {observability_path}, so we need {observability_path}/observability
    remote_obs_conf_dir = f"{observability_path}/observability"
    c.run(f"ssh {remote_user}@{remote_host} 'mkdir -p {remote_obs_conf_dir}'")

    # Copy all yaml config files
    c.run(
        f"scp docker/observability/*.yaml {remote_user}@{remote_host}:{remote_obs_conf_dir}/"
    )
    c.run(
        f"scp docker/observability/*.yml {remote_user}@{remote_host}:{remote_obs_conf_dir}/"
    )
    # Copy dashboards directory recursively
    c.run(
        f"scp -r docker/observability/dashboards {remote_user}@{remote_host}:{remote_obs_conf_dir}/"
    )

    # Sync Environment Variables (Crucial!)
    print("Syncing .env...")
    c.run(f"scp .env {remote_user}@{remote_host}:{infra_path}/.env")
    c.run(f"scp .env {remote_user}@{remote_host}:{app_path}/.env")
    c.run(f"scp .env {remote_user}@{remote_host}:{watchdog_path}/.env")

    print("\n--- 2. Orchestrating Remote Stacks ---")
    # Ensure Network Exists
    c.run(f"ssh {remote_user}@{remote_host} 'docker network create trader-net || true'")

    # Cleanup old containers (Migration Step)
    if nuke:
        print("Cleaning up potential conflicts (NUKE MODE)...")
        c.run(
            f"ssh {remote_user}@{remote_host} 'docker rm -f trader-v2 trader-v2-ui trader-v2-watchdog trader-redis trader-streamer 2>/dev/null || true'"
        )

    print("Restarting Observability...")
    c.run(
        f"ssh {remote_user}@{remote_host} 'docker compose -p trader-observability -f {observability_path}/compose.yaml up -d --pull always --remove-orphans'"
    )

    print("Restarting Infra...")
    c.run(
        f"ssh {remote_user}@{remote_host} 'docker compose -p trader-infra -f {infra_path}/compose.yaml up -d --pull always --remove-orphans'"
    )

    print("Restarting App...")
    c.run(
        f"ssh {remote_user}@{remote_host} 'docker compose -p trader-app -f {app_path}/compose.yaml up -d --pull always --remove-orphans'"
    )

    print("Restarting Watchdog...")
    c.run(
        f"ssh {remote_user}@{remote_host} 'docker compose -p trader-watchdog -f {watchdog_path}/compose.yaml up -d --pull always --remove-orphans'"
    )

    print("\nDeployment Complete.")

    if tag:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M")
        tag_name = f"release/prod-{timestamp}"
        print(f"\n--- Tagging Release: {tag_name} ---")
        try:
            c.run(f"git tag {tag_name}")
            # Update floating 'prod' tag
            c.run("git tag -f prod")
            print("Local tags updated.")
        except Exception as e:
            print(f"Warning: Failed to create tags: {e}")


@task
def build(c):
    """
    Build the Docker image locally (without pushing).
    """
    image_name = "trader-v2"
    git_sha = c.run("git rev-parse HEAD", hide=True).stdout.strip()

    print(f"Building {image_name} (SHA: {git_sha[:7]})...")
    c.run(f"docker build --build-arg GIT_COMMIT_SHA={git_sha} -t {image_name}:latest .")


@task
def ui(c):
    """
    Start the Reflex UI dashboard locally.
    """
    print("Starting Trader V2 Dashboard (Reflex)...")
    c.run("cd dashboard && reflex run")


@task
def check(c):
    """
    Run all quality checks: linting, types, and tests.
    """
    print("--- Running Ruff Check ---")
    c.run("ruff check .")

    print("\n--- Running Type Check ---")
    c.run("ty check")

    print("\n--- Running Tests ---")
    c.run("pytest")


@task
def seed(c):
    """
    Populate the database with sample data for UI demonstration.
    """
    print("Seeding database with demo data...")
    c.run("PYTHONPATH=. uv run python app/database/seeder.py")


@task
def logs(c, limit=100, host="local", follow=True):
    """
    Stream unified logs from all stacks via Loki.
    host: 'local' (default) or 'prod' (192.168.0.191)
    follow: True (default) to tail, False to print history and exit.
    """
    if host == "prod":
        loki_base = "http://192.168.0.191:3100"
    else:
        loki_base = "http://localhost:3100"

    loki_url = f"{loki_base}/loki/api/v1/query_range"
    query = '{project=~"trader-(app|infra|watchdog|observability)"}'

    print(f"--- Streaming Logs from Loki ({host.upper()}) ---")
    last_ts_ns = 0

    def format_log_line(prefix, line):
        import json

        try:
            # Try to parse as JSON (Loguru format)
            data = json.loads(line)
            if isinstance(data, dict) and "record" in data:
                # Format: [TIME] [PREFIX] [LEVEL] - MESSAGE
                level = data["record"].get("level", {}).get("name", "INFO")
                msg = data["record"].get("message", "")

                # Filter out Watchdog INFO noise
                if prefix == "trader-v2-watchdog" and level == "INFO":
                    return None

                return f"[{prefix:<20}] {level:<8} | {msg}"
            elif isinstance(data, dict) and "text" in data:
                return f"[{prefix:<20}] {data['text'].strip()}"
        except Exception:
            pass
        # Fallback to raw line
        return f"[{prefix:<20}] {line.strip()}"

    # 1. Get Initial History (Backward from NOW)
    try:
        now_ns = int(time.time() * 1e9)
        params = {
            "query": query,
            "limit": limit,
            "end": now_ns,
            "direction": "BACKWARD",
        }
        resp = requests.get(loki_url, params=params, timeout=5)
        data = resp.json()
        result = data.get("data", {}).get("result", [])

        initial_logs = []
        for stream in result:
            prefix = stream["stream"].get("container", "unknown")
            for entry in stream["values"]:
                ts = int(entry[0])
                initial_logs.append((ts, prefix, entry[1]))

        # Sort history Forward
        initial_logs.sort(key=lambda x: x[0])
        for ts, prefix, line in initial_logs:
            dt = datetime.fromtimestamp(ts / 1e9).strftime("%H:%M:%S")
            formatted = format_log_line(prefix, line)
            if formatted:
                print(f"[{dt}] {formatted}")
            last_ts_ns = max(last_ts_ns, ts)

    except Exception as e:
        print(f"Error fetching history: {e}")

    if not follow:
        return

    # 2. Tail Loop (Forward from last_ts)
    try:
        while True:
            time.sleep(1.0)
            if last_ts_ns == 0:
                last_ts_ns = int(time.time() * 1e9)

            params = {"query": query, "start": last_ts_ns + 1, "direction": "FORWARD"}
            try:
                resp = requests.get(loki_url, params=params, timeout=2)
                data = resp.json()
                result = data.get("data", {}).get("result", [])

                new_logs = []
                for stream in result:
                    prefix = stream["stream"].get("container", "unknown")
                    for entry in stream["values"]:
                        ts = int(entry[0])
                        new_logs.append((ts, prefix, entry[1]))

                new_logs.sort(key=lambda x: x[0])
                for ts, prefix, line in new_logs:
                    dt = datetime.fromtimestamp(ts / 1e9).strftime("%H:%M:%S")
                    formatted = format_log_line(prefix, line)
                    if formatted:
                        print(f"[{dt}] {formatted}")
                    last_ts_ns = max(last_ts_ns, ts)
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\nStopped.")

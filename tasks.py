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
    Start the full 4-stack environment (Logging, Infra, App, Watchdog) locally.
    """
    print("--- 1. Creating Network ---")
    c.run("docker network create trader-net || true")

    print("\n--- 2. Starting Logging Stack (Loki, Promtail, Grafana) ---")
    c.run(
        "docker compose --project-directory . -p trader-logging -f docker/docker-compose.logging.yml up -d"
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
        "docker compose --project-directory . -p trader-watchdog -f docker/docker-compose.watchdog.yml down"
    )

    print("\n--- 2. Stopping App Stack ---")
    c.run(
        "docker compose --project-directory . -p trader-app -f docker/docker-compose.app.yml down"
    )

    print("\n--- 3. Stopping Infra Stack ---")
    c.run(
        "docker compose --project-directory . -p trader-infra -f docker/docker-compose.infra.yml down"
    )

    print("\n--- 4. Stopping Logging Stack ---")
    c.run(
        "docker compose --project-directory . -p trader-logging -f docker/docker-compose.logging.yml down"
    )

    print("\nAll stacks stopped.")


@task
def deploy(c):
    """
    Deploy the 4 stacks to the production server (192.168.0.191).
    """
    remote_host = "192.168.0.191"
    remote_user = "root"  # Update if different
    base_path = "/opt/stacks"

    logging_path = f"{base_path}/trader-logging"
    infra_path = f"{base_path}/trader-infra"
    app_path = f"{base_path}/trader-app"
    watchdog_path = f"{base_path}/trader-watchdog"

    print(f"--- 1. Syncing Configs to {remote_host} ---")
    # Ensure directories exist
    c.run(
        f"ssh {remote_user}@{remote_host} 'mkdir -p {logging_path} {infra_path} {app_path} {watchdog_path} /opt/trader-v2-data'"
    )

    # Sync compose files
    c.run(
        f"scp docker/docker-compose.logging.yml {remote_user}@{remote_host}:{logging_path}/compose.yaml"
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

    # Sync logging configs
    # The compose file expects ./docker/logging/... relative to itself
    # We are placing compose.yaml in {logging_path}, so we need {logging_path}/docker/logging
    remote_logging_conf_dir = f"{logging_path}/docker/logging"
    c.run(f"ssh {remote_user}@{remote_host} 'mkdir -p {remote_logging_conf_dir}'")

    # Copy all yaml config files
    c.run(
        f"scp docker/logging/*.yaml {remote_user}@{remote_host}:{remote_logging_conf_dir}/"
    )
    # Copy dashboards directory recursively
    c.run(
        f"scp -r docker/logging/dashboards {remote_user}@{remote_host}:{remote_logging_conf_dir}/"
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
    print("Cleaning up potential conflicts...")
    c.run(
        f"ssh {remote_user}@{remote_host} 'docker rm -f trader-v2 trader-v2-ui trader-v2-watchdog trader-redis trader-streamer 2>/dev/null || true'"
    )

    # Note: We pass HOST_DATA_PATH via env on the server or in the command
    env_vars = "HOST_DATA_PATH=/opt/trader-v2-data"

    print("Restarting Logging...")
    c.run(
        f"ssh {remote_user}@{remote_host} 'docker compose -p trader-logging -f {logging_path}/compose.yaml up -d --pull always --remove-orphans'"
    )

    print("Restarting Infra...")
    c.run(
        f"ssh {remote_user}@{remote_host} '{env_vars} docker compose -p trader-infra -f {infra_path}/compose.yaml up -d --pull always --remove-orphans'"
    )

    print("Restarting App...")
    c.run(
        f"ssh {remote_user}@{remote_host} '{env_vars} docker compose -p trader-app -f {app_path}/compose.yaml up -d --pull always --remove-orphans'"
    )

    print("Restarting Watchdog...")
    c.run(
        f"ssh {remote_user}@{remote_host} '{env_vars} docker compose -p trader-watchdog -f {watchdog_path}/compose.yaml up -d --pull always --remove-orphans'"
    )

    print("\nDeployment Complete.")


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
def logs(c, limit=100, host="local"):
    """


    Stream unified logs from all stacks via Loki.


    host: 'local' (default) or 'prod' (192.168.0.191)


    """

    if host == "prod":
        loki_base = "http://192.168.0.191:3100"

    else:
        loki_base = "http://localhost:3100"

    loki_url = f"{loki_base}/loki/api/v1/query_range"

    query = '{project=~"trader-(app|infra)"}'

    print(f"--- Streaming Logs from Loki ({host.upper()}) ---")

    last_ts_ns = 0

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

            print(f"[{dt}] {prefix:<20} | {line}")

            last_ts_ns = max(last_ts_ns, ts)

    except Exception as e:
        print(f"Error fetching history: {e}")

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

                    print(f"[{dt}] {prefix:<20} | {line}")

                    last_ts_ns = max(last_ts_ns, ts)

            except Exception:
                pass

    except KeyboardInterrupt:
        print("\nStopped.")

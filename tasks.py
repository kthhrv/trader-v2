import os
import time
import requests
from datetime import datetime
from invoke import task


def get_compose_cmd(env="local", files=None):
    """
    Helper to construct the docker compose command for a specific environment.
    """
    env_file = f".env.{env}"
    if not os.path.exists(env_file):
        print(f"Error: {env_file} not found.")
        # Fallback to example if local
        if env == "local" and os.path.exists(".env.example"):
            print("Using .env.example as fallback for local dev.")
            env_file = ".env.example"
        else:
            return None

    project_name = env

    cmd = (
        f"docker compose -p {project_name} --env-file {env_file} --project-directory ."
    )

    if files:
        for f in files:
            cmd += f" -f {f}"

    # Export ENV_FILE so docker-compose can use it in yaml interpolation
    os.environ["ENV_FILE"] = env_file

    return cmd


@task
def up(c, env="local", build=False):
    """
    Start the full environment for a specific project (local, demo, live).
    Usage: inv up --env=demo
    """
    files = [
        "docker/docker-compose.infra.yml",
        "docker/docker-compose.app.yml",
        "docker/docker-compose.observability.yml",
        "docker/docker-compose.watchdog.yml",
    ]

    # Add .dev.yml overrides if local
    if env == "local":
        files.extend(
            [
                "docker/docker-compose.infra.dev.yml",
                "docker/docker-compose.app.dev.yml",
                "docker/docker-compose.watchdog.dev.yml",
            ]
        )

    build_flag = "--build" if build else ""
    cmd = get_compose_cmd(env, files)
    if not cmd:
        return

    print(f"--- Starting {env.upper()} Environment ---")
    c.run(f"{cmd} up -d {build_flag} --remove-orphans")
    print(f"\n{env.upper()} environment started. Use 'docker ps' to verify.")


@task
def down(c, env="local", volumes=False):
    """
    Stop and remove all services for a specific environment.
    """
    files = [
        "docker/docker-compose.infra.yml",
        "docker/docker-compose.app.yml",
        "docker/docker-compose.observability.yml",
        "docker/docker-compose.watchdog.yml",
    ]

    v_flag = "-v" if volumes else ""
    cmd = get_compose_cmd(env, files)
    if not cmd:
        return

    print(f"--- Stopping {env.upper()} Environment ---")
    c.run(f"{cmd} down {v_flag}")


@task
def restart(c, env="local", service=None):
    """
    Restart services in a specific environment.
    Usage: inv restart --env=live --service=trader
    """
    files = [
        "docker/docker-compose.infra.yml",
        "docker/docker-compose.app.yml",
        "docker/docker-compose.observability.yml",
        "docker/docker-compose.watchdog.yml",
    ]

    cmd = get_compose_cmd(env, files)
    if not cmd:
        return
    target = service if service else ""

    print(f"--- Restarting {service or 'all'} in {env.upper()} ---")
    c.run(f"{cmd} restart {target}")


@task
def deploy(c, env="demo", nuke=False, tag=True):
    """
    Deploy a specific environment to the production server.
    """
    if env == "local":
        print("Error: Cannot deploy 'local' environment to production.")
        return

    remote_host = "192.168.0.191"
    remote_user = "root"
    # Isolate deployment paths by environment
    base_path = f"/opt/stacks/{env}"

    print(f"--- 1. Syncing {env.upper()} Configs to {remote_host} ---")
    c.run(
        f"ssh {remote_user}@{remote_host} 'mkdir -p {base_path}/docker/observability/dashboards'"
    )

    # Sync Compose Files
    c.run(
        f"scp docker/docker-compose.*.yml {remote_user}@{remote_host}:{base_path}/docker/"
    )

    # Sync Observability Configs
    c.run(
        f"scp docker/observability/*.yaml {remote_user}@{remote_host}:{base_path}/docker/observability/"
    )
    c.run(
        f"scp docker/observability/*.yml {remote_user}@{remote_host}:{base_path}/docker/observability/"
    )
    c.run(
        f"scp -r docker/observability/dashboards {remote_user}@{remote_host}:{base_path}/docker/observability/"
    )

    # Get current git commit hash for tagging/deployment
    git_sha = c.run("git rev-parse HEAD", hide=True).stdout.strip()
    print(f"Deploying version: {git_sha}")

    # Sync Environment Variables (Sync .env.<env> to remote as .env)
    print(f"Syncing .env.{env} as .env...")
    c.run(f"scp .env.{env} {remote_user}@{remote_host}:{base_path}/.env")

    # Append dynamic deployment variables to remote .env
    c.run(
        f'ssh {remote_user}@{remote_host} \'echo "\n# --- Deployment Vars ---" >> {base_path}/.env && '
        f'echo "IMAGE_NAME=trader-v2" >> {base_path}/.env && '
        f'echo "IMAGE_TAG={git_sha}" >> {base_path}/.env\''
    )

    print(f"\n--- 2. Orchestrating {env.upper()} Remote Stack ---")

    # Generate a consolidated compose.yaml for Dockge/Portainer compatibility
    # This flattens the 'include' directives into a single file the UI can parse.
    files_flags = (
        "-f docker/docker-compose.infra.yml "
        "-f docker/docker-compose.app.yml "
        "-f docker/docker-compose.observability.yml "
        "-f docker/docker-compose.watchdog.yml"
    )

    # We must explicitly pass the env vars so 'docker compose config' can resolve them
    # into the flattened file (baking them in).
    config_cmd = (
        f"cd {base_path} && "
        f"IMAGE_TAG={git_sha} "
        f"IMAGE_NAME=trader-v2 "
        f"ENV_FILE=.env "
        f"docker compose --project-directory . --env-file .env {files_flags} config > {base_path}/compose.yaml"
    )
    c.run(f"ssh {remote_user}@{remote_host} '{config_cmd}'")

    # Run the stack using the consolidated file
    # We still pass --env-file so the running containers have access to them if needed (runtime),
    # even though build-time vars are baked in.
    remote_cmd = (
        f"cd {base_path} && "
        f"docker compose -p {env} up -d --pull always --remove-orphans"
    )

    if nuke:
        print(f"NUKE MODE: Cleaning up existing {env} containers...")
        c.run(
            f"ssh {remote_user}@{remote_host} 'docker compose -p {env} down -v || true'"
        )

    c.run(f"ssh {remote_user}@{remote_host} '{remote_cmd}'")

    print(f"\nDeployment of {env.upper()} Complete.")

    if tag:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M")
        tag_name = f"release/{env}-{timestamp}"
        print(f"\n--- Tagging Release: {tag_name} ---")
        try:
            c.run(f"git tag {tag_name}")
            c.run(f"git tag -f {env}")
            print("Local tags updated.")
        except Exception as e:
            print(f"Warning: Failed to create tags: {e}")


@task
def logs(c, env="local", service=None, limit=100, host=None, follow=True):
    """
    Stream logs from Loki for a specific environment.
    """
    # Alias prod -> live
    if env == "prod":
        env = "live"

    # Default to prod host if env is live or demo, otherwise local
    if host is None:
        if env in ["live", "demo"]:
            host = "prod"
        else:
            host = "local"
    loki_port = 3100
    if host == "prod":
        if env == "live":
            loki_port = 3102
        elif env == "demo":
            loki_port = 3101

        loki_base = f"http://192.168.0.191:{loki_port}"
    else:
        loki_base = "http://localhost:3100"

    # In our new naming, container names are {env}-{service}
    # So we can filter by {env}-.*
    query = f'{{container=~"{env}-.*"}}'
    if service:
        query = f'{{container="{env}-{service}"}}'

    loki_url = f"{loki_base}/loki/api/v1/query_range"

    print(f"--- Streaming {env.upper()} Logs from Loki ({host.upper()}) ---")
    last_ts_ns = 0

    def format_log_line(prefix, line):
        import json

        try:
            data = json.loads(line)
            if isinstance(data, dict) and "record" in data:
                level = data["record"].get("level", {}).get("name", "INFO")
                msg = data["record"].get("message", "")
                if "watchdog" in prefix and level == "INFO":
                    return None
                return f"[{prefix:<20}] {level:<8} | {msg}"
            elif isinstance(data, dict) and "text" in data:
                return f"[{prefix:<20}] {data['text'].strip()}"
        except Exception:
            pass
        return f"[{prefix:<20}] {line.strip()}"

    # 1. Get Initial History
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

    # 2. Tail Loop
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


@task
def publish(c):
    """
    Build the Docker image and push it to the registry.
    """
    registry = "192.168.0.191:5000"
    image_name = "trader-v2"

    # Get current git commit hash
    git_sha = c.run("git rev-parse HEAD", hide=True).stdout.strip()

    sha_tag = f"{registry}/{image_name}:{git_sha}"
    latest_tag = f"{registry}/{image_name}:latest"

    print(f"Building {sha_tag}...")
    c.run(
        f"docker buildx build "
        f"--build-arg GIT_COMMIT_SHA={git_sha} "
        f"-t {sha_tag} "
        f"-t {latest_tag} "
        f"--push ."
    )
    print(f"Successfully pushed {sha_tag} and {latest_tag}")


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
def cmd(c, env="demo", args=""):
    """
    Run an arbitrary command inside the remote trader container.
    Usage: inv cmd --env=demo --args="--regime --market ftse"
    """
    remote_host = "192.168.0.191"
    remote_user = "root"

    # Construct the remote command
    container_name = f"{env}-trader"
    remote_cmd = f"docker exec -it {container_name} python main.py {args}"

    print(f"--- Running on {env.upper()} ({remote_host}): {args} ---")

    # Use pty=True for interactive output (colors, progress bars, etc)
    # ssh -t forces pseudo-tty allocation
    c.run(f"ssh -t {remote_user}@{remote_host} '{remote_cmd}'", pty=True)

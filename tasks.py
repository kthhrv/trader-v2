from invoke import task


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
def deploy(c):
    """
    Deploy the 3 stacks to the production server (192.168.0.191).
    """
    remote_host = "192.168.0.191"
    remote_user = "root"  # Update if different
    base_path = "/opt/stacks"

    infra_path = f"{base_path}/trader-infra"
    app_path = f"{base_path}/trader-app"
    watchdog_path = f"{base_path}/trader-watchdog"

    print(f"--- 1. Syncing Configs to {remote_host} ---")
    # Ensure directories exist
    c.run(
        f"ssh {remote_user}@{remote_host} 'mkdir -p {infra_path} {app_path} {watchdog_path} /opt/trader-v2-data'"
    )

    # Sync compose files
    c.run(
        f"scp docker-compose.infra.yml {remote_user}@{remote_host}:{infra_path}/compose.yaml"
    )
    c.run(
        f"scp docker-compose.app.yml {remote_user}@{remote_host}:{app_path}/compose.yaml"
    )
    c.run(
        f"scp docker-compose.watchdog.yml {remote_user}@{remote_host}:{watchdog_path}/compose.yaml"
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
def up(c):
    """
    Start the full 3-stack environment (Infra, App, Watchdog) locally.
    """
    print("--- 1. Creating Network ---")
    c.run("docker network create trader-net || true")

    print("\n--- 2. Starting Infra Stack (Redis, Streamer) ---")
    c.run(
        "docker compose -p trader-infra -f docker-compose.infra.yml up -d --build --remove-orphans"
    )

    print("\n--- 3. Starting App Stack (Trader, UI) ---")
    c.run(
        "docker compose -p trader-app -f docker-compose.app.yml up -d --build --remove-orphans"
    )

    print("\n--- 4. Starting Watchdog Stack ---")
    c.run(
        "docker compose -p trader-watchdog -f docker-compose.watchdog.yml up -d --build --remove-orphans"
    )

    print("\nAll stacks started. Use 'docker ps' to verify.")


@task
def down(c):
    """
    Stop and remove all 3 stacks (Infra, App, Watchdog).
    """
    print("--- 1. Stopping Watchdog Stack ---")
    c.run("docker compose -p trader-watchdog -f docker-compose.watchdog.yml down")

    print("\n--- 2. Stopping App Stack ---")
    c.run("docker compose -p trader-app -f docker-compose.app.yml down")

    print("\n--- 3. Stopping Infra Stack ---")
    c.run("docker compose -p trader-infra -f docker-compose.infra.yml down")

    print("\nAll stacks stopped.")

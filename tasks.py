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
    c.run(f"docker build --build-arg GIT_COMMIT_SHA={git_sha} -t {full_image_name} .")

    print(f"Pushing {full_image_name}...")
    c.run(f"docker push {full_image_name}")


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

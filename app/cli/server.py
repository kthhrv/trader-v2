import asyncio
from app.core.logger import logger
from app.core.container import Container
from app.cli.schedule import run_scheduler


async def run_server_mode(dry_run: bool):
    """
    Starts the centralized Command Listener AND the background Scheduler.
    This turns the container into an execution server.
    """
    logger.info("Starting Trader V2 Execution Server...")

    # 1. Start Command Listener
    listener = Container.create_command_listener(dry_run=dry_run)
    listener_task = asyncio.create_task(listener.start())

    # 2. Start Scheduler (Background)
    # Note: run_scheduler is currently blocking (while True). We need to adapt it.
    # The existing run_scheduler has a 'while True' loop.
    # We should run it in a separate task, but we need to ensure it doesn't block the listener.

    # Actually, we should refactor run_scheduler to be non-blocking or just run it as a task.
    # But run_scheduler uses APScheduler.start() which is non-blocking, followed by a sleep loop.
    # We can just run both.

    scheduler_task = asyncio.create_task(run_scheduler(dry_run))

    await asyncio.gather(listener_task, scheduler_task)

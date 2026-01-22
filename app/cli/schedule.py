import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.logger import logger
from app.core.markets import MARKET_CONFIGS
from app.cli.trade import run_market_strategy


async def run_scheduler(dry_run: bool):
    """
    Starts the background scheduler for all configured markets.
    """
    logger.info("Starting Scheduler Mode...")
    scheduler = AsyncIOScheduler()

    for market_key, config in MARKET_CONFIGS.items():
        schedule = config.get("schedule")
        timezone = config.get("timezone", "UTC")

        if schedule:
            trigger = CronTrigger(
                day_of_week=schedule.get("day_of_week", "mon-fri"),
                hour=schedule.get("hour"),
                minute=schedule.get("minute"),
                timezone=timezone,
            )
            # Scheduler implies yes=True (Fully Automated)
            scheduler.add_job(
                run_market_strategy,
                trigger,
                args=[market_key, dry_run, False, True],  # analyst_mode=False, yes=True
                id=f"strategy_{market_key}",
                replace_existing=True,
            )
            logger.info(
                f"Scheduled {config['name']} ({market_key}) @ {schedule['hour']}:{schedule['minute']} {timezone}"
            )

    scheduler.start()
    logger.info("Scheduler started. Press Ctrl+C to exit.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass

import asyncio
import sys
import argparse
from app.core.logger import logger, configure_logging
from app.database.session import init_db
from app.core.markets import MARKET_CONFIGS
from app.cli.trade import run_market_strategy
from app.cli.schedule import run_scheduler
from app.cli.diagnostics import (
    run_post_mortem,
    run_news_check,
    run_debug_search,
    fetch_news_print,
)


async def main():
    parser = argparse.ArgumentParser(description="Trader V2")
    parser.add_argument(
        "--market",
        type=str,
        choices=list(MARKET_CONFIGS.keys()),
        help="Market key to trade",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate trades")
    parser.add_argument(
        "--analyst", action="store_true", help="Generate trading plan without executing"
    )
    parser.add_argument(
        "--news", action="store_true", help="Fetch and print news for the market"
    )
    parser.add_argument(
        "--news-check",
        action="store_true",
        help="Run a health check on news fetching for all markets.",
    )
    parser.add_argument(
        "--with-rating",
        action="store_true",
        help="When using --news-check, ask Gemini to rate the relevance/quality of the news.",
    )
    parser.add_argument(
        "--post-mortem", type=str, help="Run post-mortem analysis on a deal ID"
    )
    parser.add_argument(
        "--init-db", action="store_true", help="Initialize database tables"
    )
    parser.add_argument(
        "--scheduler",
        action="store_true",
        help="Start the background scheduler for all markets",
    )
    parser.add_argument("--debug-search", type=str, help="Search for markets (debug)")
    parser.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt for execution"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging (INFO level)",
    )

    # Print help and exit if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    # 0. Configure Logging
    configure_logging(args.verbose)

    # 1. Init DB (Auto-heal)
    if not args.debug_search:
        await init_db()

    # 2. Dispatch Commands
    if args.scheduler:
        # Scheduler usually needs logs, so maybe force verbose if logic demands,
        # but user can control it.
        await run_scheduler(args.dry_run)
        return

    if args.post_mortem:
        await run_post_mortem(args.post_mortem)
        return

    if args.debug_search:
        await run_debug_search(args.debug_search)
        return

    if args.news_check:
        await run_news_check(args.with_rating, args.market)
        return

    if args.news:
        if not args.market:
            logger.error("Please specify --market with --news")
            return
        await fetch_news_print(args.market)
        return

    # 3. Single Market Run (Interactive/One-off)
    if args.market:
        await run_market_strategy(args.market, args.dry_run, args.analyst, args.yes)
        return

    logger.error("Please specify a valid command (use -h for help).")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

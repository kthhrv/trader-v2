from typing import Optional
from sqlmodel import select
from app.core.logger import logger
from app.database.session import async_session_maker
from app.database.models import TradeExecution
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService
from app.adapters.news_client import NewsClient
from app.adapters.notification import HomeAssistantNotifier
from app.core.markets import MARKET_CONFIGS


async def run_post_mortem(deal_id: str):
    """
    Runs a post-mortem analysis for a specific deal ID.
    """
    logger.info(f"Starting Post-Mortem for Deal ID: {deal_id}")

    execution = None
    async with async_session_maker() as session:
        statement = select(TradeExecution).where(TradeExecution.deal_id == deal_id)
        results = await session.execute(statement)
        execution = results.scalars().first()

        if execution:
            await session.refresh(execution, ["signal"])

    if not execution:
        logger.error(f"Execution not found for Deal ID: {deal_id}")
        return

    logger.info(
        f"Found Trade: {execution.deal_id} ({execution.direction}) - Outcome: {execution.pnl}"
    )

    analyst = GeminiService()

    trade_log_dict = {
        "deal_id": execution.deal_id,
        "entry": execution.fill_price,
        "action": execution.direction,
        "pnl": execution.pnl,
        "reasoning": execution.signal.reasoning if execution.signal else "N/A",
    }

    execution_data_dict = execution.model_dump(mode="json")
    report = await analyst.generate_post_mortem(trade_log_dict, execution_data_dict)

    if report:
        print("\n" + "=" * 60)
        print("POST-MORTEM ANALYSIS REPORT")
        print("=" * 60)
        print(f"Followed Plan: {report.did_follow_plan}")
        print(f"Stop Loss Check: {report.stop_loss_critique}")
        print(f"Slippage Impact: {report.slippage_impact}")
        print(f"Reasoning Check: {report.reasoning_quality}")
        print(f"Verdict: {report.verdict}")
        print("-" * 60)
        print(f"KEY LESSON: {report.key_lesson}")
        print("=" * 60 + "\n")
    else:
        logger.error("Failed to generate post-mortem report.")


async def run_news_check(with_rating: bool, market_key: Optional[str] = None):
    """
    Runs a health check on news fetching, optionally with AI rating.
    """
    logger.info("Running News Health Check...")
    fetcher = NewsClient()
    analyst = GeminiService() if with_rating else None

    print(f"\n{'=' * 80}")
    print(f"{'NEWS HEALTH CHECK':^80}")
    if with_rating:
        print(f"{'(with AI Quality Audit)':^80}")
    print(f"{'=' * 80}")

    passed = 0
    failed = 0

    def get_query(epic):
        if "FTSE" in epic:
            return "FTSE 100 UK Economy"
        elif "SPX" in epic or "US500" in epic or "SPTRD" in epic:
            return "S&P 500 US Economy"
        elif "GBP" in epic:
            return "GBP USD Forex"
        elif "EUR" in epic:
            return "EUR USD Forex"
        elif "DAX" in epic or "DE30" in epic:
            return "DAX 40 Germany Economy"
        elif "NIKKEI" in epic:
            return "Nikkei 225 Japan Economy"
        elif "ASX" in epic:
            return "ASX 200 Australia Economy"
        elif "NASDAQ" in epic:
            return "Nasdaq 100 US Tech Sector"
        return "Global Financial Markets"

    targets = MARKET_CONFIGS.items()
    if market_key:
        if market_key in MARKET_CONFIGS:
            targets = [(market_key, MARKET_CONFIGS[market_key])]
        else:
            logger.error(f"Unknown market: {market_key}")
            return

    for market, config in targets:
        query = get_query(config["epic"])
        print(f"\nChecking [{market.upper()}] Query: '{query}'...")
        try:
            result = await fetcher.fetch_news(query, market=market)

            if "No recent news found" in result:
                print("  [WARN] No news returned.")
                failed += 1
            else:
                lines = result.split("\n")
                count = len([line for line in lines if line.strip()])
                print(f"  [PASS] Retrieved content (~{count} lines).")
                print(f"  Sample: {result[:70]}...")

                if analyst:
                    print("  Running AI Audit...", end="", flush=True)
                    quality = await analyst.assess_news(result, market)
                    if quality:
                        print(
                            f"\r  [AI RATING] Score: {quality.score}/10 | Clarity: {quality.sentiment_clarity}"
                        )
                        print(f"  Reasoning: {quality.reasoning}")
                        if quality.score < 5:
                            print("  [WARN] Low quality news detected.")
                    else:
                        print("\r  [AI ERROR] Could not rate news.")

                passed += 1
        except Exception as e:
            print(f"  [FAIL] Exception: {e}")
            failed += 1

    print(f"\nSummary: {passed} Passed, {failed} Failed.")


async def run_debug_search(term: str):
    """
    Searches for markets in IG.
    """
    async with AsyncIGClient() as ig_client:
        results = await ig_client.search_markets(term, env_type="DEMO")
        logger.info(f"Search Results: {results}")


async def fetch_news_print(market_key: str):
    """
    Fetches and prints news for a specific market.
    """
    news_client = NewsClient()
    config = MARKET_CONFIGS.get(market_key)
    if not config:
        logger.error(f"Invalid market: {market_key}")
        return

    epic = config["epic"]
    query = "Global Financial Markets"
    if "FTSE" in epic:
        query = "FTSE 100 UK Economy"
    elif "SPX" in epic:
        query = "S&P 500 US Economy"

    print(f"Fetching news for {market_key}...")
    summary = await news_client.fetch_news(query, market=market_key)
    print(summary)


async def run_test_alert():
    """
    Sends a test notification to Home Assistant.
    """
    logger.info("Sending Test Alert to HA...")
    notifier = HomeAssistantNotifier()
    await notifier.send_notification(
        title="TRADER V2 Test",
        message="This is a test notification from the V2 system.",
        priority="high",
    )
    logger.info("Test Alert Sent.")


async def run_countdown():
    """
    Shows time remaining until the next market open.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now_utc = datetime.now(ZoneInfo("UTC"))
    next_opens = []

    for name, cfg in MARKET_CONFIGS.items():
        schedule = cfg.get("schedule")
        if not schedule:
            continue

        tz = ZoneInfo(cfg.get("timezone", "UTC"))
        now_tz = now_utc.astimezone(tz)

        # Calculate next occurrence of this time
        target = now_tz.replace(
            hour=schedule["hour"], minute=schedule["minute"], second=0, microsecond=0
        )

        # If it's already passed today, or it's a weekend, find the next Mon-Fri open
        if now_tz >= target or now_tz.weekday() >= 5:  # 5=Sat, 6=Sun
            days_to_add = 1
            while True:
                candidate = target + timedelta(days=days_to_add)
                if candidate.weekday() < 5 and candidate > now_tz:
                    target = candidate
                    break
                days_to_add += 1

        next_opens.append((name, target.astimezone(ZoneInfo("UTC"))))

    next_opens.sort(key=lambda x: x[1])

    if next_opens:
        next_market, next_time = next_opens[0]
        remaining = next_time - now_utc

        # Clean up the string representation
        rem_str = str(remaining).split(".")[0]

        print(f"\nNext Open: {next_market.upper()}")
        print(f"Time:      {next_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"Countdown: T-{rem_str}\n")
    else:
        print("No market opens scheduled.")

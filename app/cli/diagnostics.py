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
from app.services.scorecard import ScorecardService


async def run_regime_check(market_key: str):
    """
    Analyzes and prints the current V3 Market Regime for a given market.
    """
    from app.services.analyzer import MarketAnalyzer
    from app.services.market_data import MarketDataService
    from app.services.collector import CollectorService

    logger.info(f"Checking Regime for {market_key}...")

    config = MARKET_CONFIGS.get(market_key)
    if not config:
        logger.error(f"Invalid market: {market_key}")
        return

    epic = config["epic"]

    # Initialize Stack
    client = AsyncIGClient.get_instance()
    collector = CollectorService(client)
    market_data = MarketDataService(client, collector)
    # We don't need news or gemini for just the regime calc
    analyzer = MarketAnalyzer(market_data, None, None)  # type: ignore

    try:
        regime = await analyzer._build_market_regime(epic)

        if not regime:
            print("Failed to build regime (Insufficient data?)")
            return

        print(f"\n{'=' * 60}")
        print(f"MARKET REGIME REPORT: {market_key.upper()} ({epic})")
        print(f"{'=' * 60}")
        print(f"Price:      {regime.current_price}")
        print(f"Time (UTC): {regime.timestamp.strftime('%H:%M:%S')}")
        print(f"{'-' * 60}")

        ind = regime.indicators
        st = regime.state

        print(
            f"Trend:      {st.trend} (EMA20: {ind.ema_20:.2f} | Slope: {ind.ema_slope:.3f})"
        )
        print(f"Volatility: {st.volatility} (Ratio: {st.volatility_ratio:.2f})")
        print(
            f"Condition:  {'PARABOLIC' if st.is_parabolic else 'Normal'} (Ext: {ind.extension_factor:.2f}x ATR)"
        )
        print(f"Choppy:     {st.is_choppy} (ADX: {ind.adx_14:.2f})")
        print(f"Volume:     RVOL {ind.rvol:.2f}")
        print(f"RSI:        {ind.rsi_14:.2f}")

        # Sentinel Trigger Check
        triggers = []
        if ind.rvol > 2.0:
            triggers.append(f"RVOL_SPIKE ({ind.rvol:.1f}x)")
        if st.is_parabolic:
            triggers.append(f"PARABOLIC ({ind.extension_factor:.1f}x)")

        if triggers:
            print(f"\n🚨 SENTINEL WOULD TRIGGER: {', '.join(triggers)}")
        else:
            print("\n✅ Sentinel Status: QUIET")

        print(f"{'=' * 60}\n")

    except Exception as e:
        logger.exception(f"Regime check failed: {e}")


async def run_scorecard():
    """
    Generates and prints the Performance Scorecard.
    """
    stats = await ScorecardService.get_scorecard_data()
    ScorecardService.generate_report(stats)


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


async def run_recent_trades(limit: int = 5):
    """
    Fetches and displays recent trades with detailed "awesome" formatting.
    """
    import shutil
    from app.database.queries import get_recent_trades_joined

    trades = await get_recent_trades_joined(limit)

    if not trades:
        print("No recent trades found.")
        return

    term_width = shutil.get_terminal_size((80, 20)).columns
    # Ensure a reasonable minimum/maximum if needed, but term_width is usually safe.
    # We'll use min(term_width, 100) to avoid excessive spanning on ultra-wide monitors,
    # but stick to term_width for standard terminals.
    # Actually, full width is fine for separators.

    sep = "=" * term_width
    sub_sep = (
        "-" * 40
    )  # Keep partial separators fixed or relative? Fixed is safer for data columns.

    print(f"\n{sep}")
    print(f"{'RECENT TRADES PERFORMANCE':^{term_width}}")
    print(f"{sep}\n")

    total_pnl = 0.0
    wins = 0
    losses = 0

    for execution, signal in trades:
        # ... (rest of loop)

        # Colors
        GREEN = "\033[92m"
        RED = "\033[91m"
        YELLOW = "\033[93m"
        BLUE = "\033[94m"
        RESET = "\033[0m"
        BOLD = "\033[1m"

        # Determine Outcome Color
        pnl = execution.pnl if execution.pnl is not None else 0.0
        pnl_color = GREEN if pnl > 0 else (RED if pnl < 0 else YELLOW)
        outcome_str = f"{pnl_color}{execution.outcome_status}{RESET}"
        pnl_str = f"{pnl_color}£{pnl:.2f}{RESET}"

        # Stats
        if execution.outcome_status == "WIN":
            wins += 1
            total_pnl += pnl
        elif execution.outcome_status == "LOSS":
            losses += 1
            total_pnl += pnl

        # Duration
        duration_str = "Active"
        if execution.fill_time and execution.exit_time:
            duration = execution.exit_time - execution.fill_time
            # Format nicely (HH:MM:SS)
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # R-Multiple (approximate)
        r_multiple = "N/A"
        if execution.initial_stop_loss and execution.fill_price:
            risk = abs(execution.fill_price - execution.initial_stop_loss)
            if risk > 0 and pnl != 0:
                try:
                    r_val = pnl / (risk * execution.size)
                    r_multiple = f"{r_val:.1f}R"
                except Exception:
                    pass

        # Strategy Name
        strategy = signal.strategy_name if signal else "MANUAL/UNKNOWN"
        symbol = signal.symbol if signal else "UNKNOWN"
        reasoning = (
            signal.reasoning[:120] + "..."
            if signal and signal.reasoning
            else "No reasoning recorded."
        )

        # Action Arrow
        arrow = "⬆" if execution.direction == "BUY" else "⬇"
        dir_color = GREEN if execution.direction == "BUY" else RED

        print(
            f"{BOLD}Deal ID:{RESET} {execution.deal_id} | {dir_color}{arrow} {execution.direction}{RESET} {symbol} ({strategy})"
        )
        print(
            f"Time: {execution.fill_time.strftime('%Y-%m-%d %H:%M:%S')} UTC | Duration: {duration_str}"
        )
        print(f"{sub_sep}")
        print(
            f"Entry: {execution.fill_price}  ->  Exit: {execution.exit_price or 'Active'}"
        )
        print(
            f"Size:  {execution.size}      |  Result: {outcome_str} ({pnl_str}) [{r_multiple}]"
        )
        print(
            f"Stops: {execution.initial_stop_loss} (Init) -> {execution.current_stop_loss} (Final)"
        )
        if signal:
            print(
                f"Plan:  Target {signal.take_profit or 'Open'} | Conf: {signal.confidence}"
            )
            print(f"{BLUE}AI Reasoning:{RESET} {reasoning}")
        print(f"{'_' * term_width}\n")

    # Summary Footer
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    tot_color = GREEN if total_pnl > 0 else (RED if total_pnl < 0 else RESET)

    print(f"SUMMARY (Last {limit})")
    print(
        f"Total PnL: {tot_color}£{total_pnl:.2f}{RESET} | Win Rate: {win_rate:.1f}% ({wins}W-{losses}L)"
    )
    print(f"{'=' * term_width}\n")


async def run_debug_search(term: str):
    """
    Searches for markets in IG.
    """
    async with AsyncIGClient.get_instance() as ig_client:
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
    elif "SPX" in epic or "US500" in epic or "SPTRD" in epic:
        query = "S&P 500 US Economy"
    elif "DAX" in epic or "DE30" in epic:
        query = "DAX 40 Germany Economy"
    elif "NIKKEI" in epic:
        query = "Nikkei 225 Japan Economy"
    elif "ASX" in epic:
        query = "ASX 200 Australia Economy"
    elif "NASDAQ" in epic:
        query = "Nasdaq 100 US Tech Sector"

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
    from app.services.market_status import MarketStatusService

    market_status = MarketStatusService()
    now_utc = datetime.now(ZoneInfo("UTC"))
    next_opens = []

    for name, cfg in MARKET_CONFIGS.items():
        schedule = cfg.get("schedule")
        epic = cfg.get("epic")
        if not schedule or not epic:
            continue
        tz = ZoneInfo(cfg.get("timezone", "UTC"))
        now_tz = now_utc.astimezone(tz)

        # Calculate next occurrence of this time today
        target = now_tz.replace(
            hour=schedule["hour"], minute=schedule["minute"], second=0, microsecond=0
        )

        # Start checking from today (or tomorrow if time passed)
        check_date = target
        if now_tz >= target:
            check_date = target + timedelta(days=1)

        # Find the next valid trading day (Not Weekend, Not Holiday)
        while True:
            # 1. Weekend Check
            if check_date.weekday() >= 5:  # 5=Sat, 6=Sun
                check_date += timedelta(days=1)
                continue

            # 2. Holiday Check
            # is_holiday expects the epic to look up the country and check that specific date
            # We temporarily mock datetime.now inside the service? No, let's use the internal logic.
            # Actually, MarketStatusService.is_holiday checks 'datetime.now(market_tz).date()' internally.
            # We need a way to check a SPECIFIC date.
            # The service doesn't expose `is_date_holiday(date, epic)`.
            # We will refactor lightly to access the holiday check logic or instantiate the check properly.

            # Since we cannot easily change MarketStatusService signature right here without a bigger refactor,
            # we will inspect the holiday objects directly since they are public attributes of the service instance.
            country = market_status._get_country_code(epic)
            is_holiday_date = False
            target_date_obj = check_date.date()

            if country == "GB" and target_date_obj in market_status.uk_holidays:
                is_holiday_date = True
            elif country == "US" and target_date_obj in market_status.us_holidays:
                is_holiday_date = True
            elif country == "JP" and target_date_obj in market_status.jp_holidays:
                is_holiday_date = True
            elif country == "DE" and target_date_obj in market_status.de_holidays:
                is_holiday_date = True
            elif country == "AU" and target_date_obj in market_status.au_holidays:
                is_holiday_date = True

            # Holiday Season Check
            if market_status._is_holiday_season(target_date_obj):
                is_holiday_date = True

            if is_holiday_date:
                check_date += timedelta(days=1)
                continue

            # Found a valid date!
            target = check_date
            break

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

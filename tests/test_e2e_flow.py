import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlmodel import select
from datetime import datetime, timedelta, timezone

from app.database import session as db_session
from app.database.session import init_db
from app.database.models import TradeExecution
from app.adapters.gemini_service import GeminiService, TradingSignal, Action
from app.adapters.news_client import NewsClient
from app.services.market_data import MarketDataService
from app.services.collector import CollectorService
from app.services.streamer import StreamerService
from app.services.trader import StrategyEngine
from app.services.analyzer import MarketAnalyzer
from app.services.risk import RiskManager
from app.services.executor import TradeExecutor


@pytest.mark.asyncio
async def test_full_trading_flow_e2e_mocked_adapter():
    """
    Tests full lifecycle: Entry -> Trail Stop -> Trail Stop -> Exit.
    Uses AsyncMock for IGClient to verify logic flow without network brittleness.
    """
    await init_db()

    # 1. Mock IG Client
    mock_ig = MagicMock()
    mock_ig.authenticate = AsyncMock()
    mock_ig.get_account_balance = AsyncMock(return_value=10000.0)

    # Mock Order Response
    mock_ig.create_order = AsyncMock(
        return_value={"dealReference": "REF123", "dealId": "DEAL456", "level": 7015}
    )

    # Mock Position Update (Trailing Stop)
    mock_ig.update_open_position = AsyncMock(return_value={"status": "ACCEPTED"})

    # Mock Historical Prices
    def make_candle(price, time_offset_min=0, time_offset_days=0):
        t = datetime.now() - timedelta(minutes=time_offset_min, days=time_offset_days)
        return {
            "snapshotTime": t.strftime("%Y/%m/%d %H:%M:%S"),
            "openPrice": {"bid": price, "ask": price},
            "highPrice": {"bid": price + 10, "ask": price + 10},
            "lowPrice": {"bid": price - 10, "ask": price - 10},
            "closePrice": {"bid": price + 5, "ask": price + 5},
            "lastTradedVolume": 100,
        }

    prices_15m = {
        "prices": [make_candle(7000, time_offset_min=i * 15) for i in range(50)]
    }
    prices_5m = {
        "prices": [make_candle(7000, time_offset_min=i * 5) for i in range(24)]
    }
    prices_1m = {"prices": [make_candle(7000, time_offset_min=i) for i in range(15)]}
    prices_day = {"prices": [make_candle(6900, time_offset_days=i) for i in range(5)]}

    async def fetch_prices_side_effect(epic, resolution, num_points, env_type="LIVE"):
        if resolution == "MINUTE_15":
            return prices_15m
        elif resolution == "MINUTE_5":
            return prices_5m
        elif resolution == "MINUTE":
            return prices_1m
        elif resolution == "DAY":
            return prices_day
        return {"prices": []}

    mock_ig.fetch_historical_prices = AsyncMock(side_effect=fetch_prices_side_effect)

    # 2. Instantiate Real Services with Mocked Adapter
    collector = CollectorService(mock_ig)
    market_data = MarketDataService(mock_ig, collector)

    news_client = MagicMock(spec=NewsClient)
    news_client.fetch_news = AsyncMock(return_value="Bullish News")

    analyst = MagicMock(spec=GeminiService)
    # AI Decides BUY
    analyst.analyze_market = AsyncMock(
        return_value=TradingSignal(
            ticker="FTSE100",
            action=Action.BUY,
            entry=7010,
            stop_loss=6990,
            size=1.0,
            atr=20.0,
            use_trailing_stop=True,
            confidence="high",
            reasoning="Go",
        )
    )

    streamer = MagicMock(spec=StreamerService)

    # Generator yielding price ticks
    async def mock_stream(epic):
        # Entry at 7015 (offer)
        yield {"type": "price_update", "bid": 7010, "offer": 7015}

        # Risk is 7015 - 6990 = 25 points. 1.5R = 37.5 points.
        # Need price >= 7015 + 37.5 = 7052.5 to trigger breakeven.

        # Move price up to trigger breakeven
        yield {"type": "price_update", "bid": 7060, "offer": 7075}

        # Now at Breakeven (Stop = 7015). Trail distance is 3 * ATR = 3 * 20 = 60.
        # Market Price 7060 - 60 = 7000. Not better than 7015.

        # Move price higher to trigger trailing stop
        yield {"type": "price_update", "bid": 7080, "offer": 7095}
        # Market Price 7080 - 60 = 7020. Better than 7015.

    streamer.stream = mock_stream

    # Instantiate Sub-Services
    risk_manager = RiskManager(mock_ig)
    market_analyzer = MarketAnalyzer(market_data, news_client, analyst)
    trade_executor = TradeExecutor(mock_ig, streamer, dry_run=False)

    # Mock Market Status
    mock_status = MagicMock()
    mock_status.is_holiday.return_value = False

    engine = StrategyEngine(
        analyzer=market_analyzer,
        risk_manager=risk_manager,
        executor=trade_executor,
        market_status=mock_status,
        analyst_mode=False,
    )

    # Mock datetime to simulate passage of time for throttling
    # We need an infinite source of increasing time because the stream restarts
    # and has multiple ticks.
    import itertools

    initial_time = datetime.now(timezone.utc).timestamp()

    # Increment by 10s every call to ensure > 5s throttle is always passed
    time_gen = itertools.count(start=initial_time, step=10.0)

    # We need to mock datetime within app.services.executor
    with patch("app.services.executor.datetime") as mock_datetime:
        # Mock now().timestamp()
        mock_datetime.now.return_value.timestamp.side_effect = time_gen
        mock_datetime.now.return_value.tzinfo = timezone.utc  # Keep tz info

        # Run Strategy
        await engine.run_strategy("london")

    # 4. Verification
    async with db_session.async_session_maker() as session:
        execution = (await session.execute(select(TradeExecution))).scalars().first()
        assert execution is not None, "Trade execution not found in DB"
        assert execution.deal_id == "DEAL456"
        assert execution.initial_stop_loss == 6990
        # Should have moved to BE (7015) then trailed to 7020
        assert execution.current_stop_loss == 7020

    assert mock_ig.create_order.called
    assert mock_ig.update_open_position.call_count == 2
    assert mock_ig.get_account_balance.called

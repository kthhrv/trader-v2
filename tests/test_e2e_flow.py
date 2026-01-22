import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlmodel import select
from datetime import datetime, timedelta

from app.database.session import init_db, async_session_maker
from app.database.models import TradeExecution
from app.adapters.gemini_service import GeminiService, TradingSignal, Action
from app.adapters.news_client import NewsClient
from app.services.market_data import MarketDataService
from app.services.collector import CollectorService
from app.services.streamer import StreamerService
from app.services.trader import StrategyEngine


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

    # Mock Historical Prices (Sequence: MINUTE_15, DAY)
    # We need to construct the responses CollectorService expects
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
    prices_day = {"prices": [make_candle(6900, time_offset_days=i) for i in range(5)]}

    # Configure side_effect for fetch_historical_prices to return different data based on resolution
    async def fetch_prices_side_effect(epic, resolution, num_points, env_type="LIVE"):
        if resolution == "MINUTE_15":
            return prices_15m
        elif resolution == "DAY":
            return prices_day
        return {"prices": []}

    mock_ig.fetch_historical_prices = AsyncMock(side_effect=fetch_prices_side_effect)

    # 2. Instantiate Real Services with Mocked Adapter
    # Collector needs the mock client
    collector = CollectorService(mock_ig)
    # MarketData needs the mock client AND the collector
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

    # Generator yielding price ticks to trigger entry and trails
    async def mock_stream(epic):
        # 1. Trigger Entry (Offer 7015 >= 7010)
        yield {"type": "price_update", "bid": 7000, "offer": 7015}
        # 2. Trail 1: Price moves up to 7045. Target Stop = 7045 - 30 = 7015. (Initial 6990)
        yield {"type": "price_update", "bid": 7045, "offer": 7060}
        # 3. Trail 2: Price moves up to 7080. Target Stop = 7080 - 30 = 7050.
        yield {"type": "price_update", "bid": 7080, "offer": 7095}

    streamer.stream = mock_stream

    engine = StrategyEngine(
        ig_client=mock_ig,
        market_data=market_data,
        analyst=analyst,
        news_client=news_client,
        streamer=streamer,
        dry_run=False,
    )

    # 3. Run Strategy
    await engine.run_strategy("london")

    # 4. Verification

    # Verify DB State
    async with async_session_maker() as session:
        execution = (await session.execute(select(TradeExecution))).scalars().first()
        assert execution is not None, "Trade execution not found in DB"
        assert execution.deal_id == "DEAL456"
        assert execution.initial_stop_loss == 6990
        # Final stop should be 7050 (After 2nd trail)
        assert execution.current_stop_loss == 7050

    # Verify Calls
    assert mock_ig.create_order.called
    assert mock_ig.update_open_position.call_count == 2
    # Verify risk check called
    assert mock_ig.get_account_balance.called

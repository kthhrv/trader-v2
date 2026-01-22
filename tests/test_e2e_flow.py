import pytest
import re
from unittest.mock import AsyncMock, MagicMock
from sqlmodel import select
from datetime import datetime, timedelta

from app.database.session import init_db, async_session_maker
from app.database.models import TradeExecution
from app.adapters.ig_client import AsyncIGClient
from app.adapters.gemini_service import GeminiService, TradingSignal, Action
from app.adapters.news_client import NewsClient
from app.services.market_data import MarketDataService
from app.services.collector import CollectorService
from app.services.streamer import StreamerService
from app.services.trader import StrategyEngine


@pytest.mark.asyncio
async def test_full_trading_flow_e2e(httpx_mock):
    """
    Tests full lifecycle: Entry -> Trail Stop -> Trail Stop -> Exit.
    """
    await init_db()

    # 1. Mock Auth
    httpx_mock.add_response(
        method="POST",
        url=re.compile(r"^https://api\.ig\.com/gateway/deal/session"),
        status_code=200,
        headers={"CST": "live_cst", "X-SECURITY-TOKEN": "live_token"},
        json={"currentAccountId": "L123", "accountType": "CFD"},
    )
    httpx_mock.add_response(
        method="POST",
        url=re.compile(r"^https://demo-api\.ig\.com/gateway/deal/session"),
        status_code=200,
        headers={"CST": "demo_cst", "X-SECURITY-TOKEN": "demo_token"},
        json={"currentAccountId": "D123", "accountType": "CFD"},
    )

    # 2. Mock Prices
    mock_prices_15m = {
        "prices": [
            {
                "snapshotTime": (datetime.now() - timedelta(minutes=15 * i)).strftime(
                    "%Y/%m/%d %H:%M:%S"
                ),
                "openPrice": {"bid": 7000},
                "highPrice": {"bid": 7010},
                "lowPrice": {"bid": 6990},
                "closePrice": {"bid": 7005},
            }
            for i in range(50)
        ]
    }
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*MINUTE_15.*"),
        status_code=200,
        json=mock_prices_15m,
    )

    mock_prices_day = {
        "prices": [
            {
                "snapshotTime": (datetime.now() - timedelta(days=i)).strftime(
                    "%Y/%m/%d %H:%M:%S"
                ),
                "openPrice": {"bid": 6900},
                "highPrice": {"bid": 7000},
                "lowPrice": {"bid": 6800},
                "closePrice": {"bid": 6950},
            }
            for i in range(5)
        ]
    }
    # Use exact URL for DAY to fix matching issues
    httpx_mock.add_response(
        method="GET",
        url="https://api.ig.com/gateway/deal/prices/IX.D.FTSE.DAILY.IP/DAY/5",
        status_code=200,
        json=mock_prices_day,
    )

    # 3. Mock Order Placement
    httpx_mock.add_response(
        method="POST",
        url=re.compile(r".*/positions/otc"),
        status_code=200,
        json={"dealReference": "REF123", "dealId": "DEAL456", "level": 7015},
    )

    # 4. Mock Trailing Stop Updates
    httpx_mock.add_response(
        method="PUT",
        url=re.compile(r".*/positions/otc/DEAL456"),
        status_code=200,
        json={"dealReference": "REF_TRAIL_1"},
    )
    httpx_mock.add_response(
        method="PUT",
        url=re.compile(r".*/positions/otc/DEAL456"),
        status_code=200,
        json={"dealReference": "REF_TRAIL_2"},
    )

    async with AsyncIGClient() as ig_client:
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)
        news_client = MagicMock(spec=NewsClient)
        news_client.fetch_news = AsyncMock(return_value="News")

        analyst = MagicMock(spec=GeminiService)
        # ATR = 20. Trail Dist = 30. Step = 10.
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
            yield {"type": "price_update", "bid": 6990, "offer": 7005}
            yield {"type": "price_update", "bid": 7000, "offer": 7015}
            yield {"type": "price_update", "bid": 7045, "offer": 7060}
            yield {"type": "price_update", "bid": 7080, "offer": 7095}

        streamer.stream = mock_stream

        engine = StrategyEngine(
            ig_client=ig_client,
            market_data=market_data,
            analyst=analyst,
            news_client=news_client,
            streamer=streamer,
            dry_run=False,
        )

        await engine.run_strategy("london")

        async with async_session_maker() as session:
            execution = (
                (await session.execute(select(TradeExecution))).scalars().first()
            )
            assert execution is not None, "Trade execution not found in DB"
            assert execution.deal_id == "DEAL456"
            assert execution.initial_stop_loss == 6990
            assert execution.current_stop_loss == 7050

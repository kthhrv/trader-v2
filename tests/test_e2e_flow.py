import pytest
import re
from unittest.mock import AsyncMock, MagicMock
from sqlmodel import select
from datetime import datetime, timedelta

from app.database.session import init_db, async_session_maker
from app.database.models import TradeSignal, TradeExecution
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
    Tests the full flow from data fetching to order placement and DB storage.
    """
    await init_db()

    # 1. Mock Auth
    httpx_mock.add_response(
        method="POST",
        url="https://demo-api.ig.com/gateway/deal/session",
        status_code=200,
        headers={"CST": "demo_cst", "X-SECURITY-TOKEN": "demo_token"},
        json={"currentAccountId": "D123", "accountType": "CFD"},
    )

    # 2. Mock Prices (Two calls: MINUTE_15 and DAY)
    # Note: StrategyEngine calls get_latest_candles for MINUTE_15 then DAY
    mock_prices = {
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

    # First call (MINUTE_15)
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*/prices/.*/MINUTE_15/.*"),
        status_code=200,
        json=mock_prices,
    )
    # Second call (DAY)
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*/prices/.*/DAY/.*"),
        status_code=200,
        json={"prices": mock_prices["prices"][:5]},
    )

    # 3. Mock Order Placement
    httpx_mock.add_response(
        method="POST",
        url=re.compile(r".*/positions/otc"),
        status_code=200,
        json={"dealReference": "REF123", "dealId": "DEAL456", "level": 7010},
    )

    # Instantiate Stack
    async with AsyncIGClient() as ig_client:
        collector = CollectorService(ig_client)
        market_data = MarketDataService(ig_client, collector)

        news_client = MagicMock(spec=NewsClient)
        news_client.fetch_news = AsyncMock(return_value="Bullish News")

        analyst = MagicMock(spec=GeminiService)
        analyst.analyze_market = AsyncMock(
            return_value=TradingSignal(
                ticker="FTSE100",
                action=Action.BUY,
                entry=7010,
                stop_loss=6900,
                size=1.0,
                atr=20.0,
                use_trailing_stop=True,
                confidence="high",
                reasoning="Go",
            )
        )

        streamer = MagicMock(spec=StreamerService)

        async def mock_stream(epic):
            if False:
                yield {}

        streamer.stream = mock_stream

        engine = StrategyEngine(
            ig_client=ig_client,
            market_data=market_data,
            analyst=analyst,
            news_client=news_client,
            streamer=streamer,
            dry_run=False,
        )

        # Run
        await engine.run_strategy("london")

        # Verify
        async with async_session_maker() as session:
            signals = (await session.execute(select(TradeSignal))).scalars().all()
            assert len(signals) == 1

            executions = (await session.execute(select(TradeExecution))).scalars().all()
            assert len(executions) == 1
            assert executions[0].deal_id == "DEAL456"

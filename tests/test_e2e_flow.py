import pytest
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
        url="https://api.ig.com/gateway/deal/session",
        status_code=200,
        headers={"CST": "live_cst", "X-SECURITY-TOKEN": "live_token"},
        json={"accountId": "L123", "accountType": "CFD"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://demo-api.ig.com/gateway/deal/session",
        status_code=200,
        headers={"CST": "demo_cst", "X-SECURITY-TOKEN": "demo_token"},
        json={"accountId": "D123", "accountType": "CFD"},
    )

    # 2. Mock 15m Prices (Unique timestamps)
    prices_15m = []
    base_time = datetime(2026, 1, 21, 10, 0, 0)
    for i in range(50):
        ts = (base_time + timedelta(minutes=15 * i)).strftime("%Y/%m/%d %H:%M:%S")
        prices_15m.append(
            {
                "snapshotTime": ts,
                "openPrice": {"bid": 7000 + i},
                "highPrice": {"bid": 7010 + i},
                "lowPrice": {"bid": 6990 + i},
                "closePrice": {"bid": 7005 + i},
            }
        )

    httpx_mock.add_response(
        method="GET",
        url="https://api.ig.com/gateway/deal/prices/IX.D.FTSE.DAILY.IP/MIN_15/50",
        status_code=200,
        json={"prices": prices_15m},
    )

    # 3. Mock Daily Prices
    prices_d = []
    for i in range(5):
        ts = (base_time - timedelta(days=5 - i)).strftime("%Y/%m/%d %H:%M:%S")
        prices_d.append(
            {
                "snapshotTime": ts,
                "openPrice": {"bid": 6900},
                "highPrice": {"bid": 7000},
                "lowPrice": {"bid": 6800},
                "closePrice": {"bid": 6950},
            }
        )

    httpx_mock.add_response(
        method="GET",
        url="https://api.ig.com/gateway/deal/prices/IX.D.FTSE.DAILY.IP/D/5",
        status_code=200,
        json={"prices": prices_d},
    )

    # 4. Mock Order Placement
    httpx_mock.add_response(
        method="POST",
        url="https://demo-api.ig.com/gateway/deal/positions/otc",
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
                reasoning="Strong momentum breakout",
            )
        )

        streamer = MagicMock(spec=StreamerService)

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
            assert signals[0].signal_decision == "BUY"

            executions = (await session.execute(select(TradeExecution))).scalars().all()
            assert len(executions) == 1
            assert executions[0].deal_id == "DEAL456"
            assert executions[0].signal_id == signals[0].id

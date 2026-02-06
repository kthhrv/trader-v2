import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from app.cli.trade import run_market_strategy
from app.adapters.gemini_service import TradingSignal, Action, EntryType


@pytest.mark.asyncio
async def test_e2e_stalking_flow():
    """
    E2E Test verifying the integration of CLI Runner + Strategy Engine + Stalking Loop.
    """

    # 1. Mock Data
    wait_signal = TradingSignal(
        ticker="SPX",
        action=Action.WAIT,
        entry=0,
        stop_loss=0,
        size=0,
        atr=0,
        use_trailing_stop=False,
        confidence="low",
        reasoning="Noise",
    )

    buy_signal = TradingSignal(
        ticker="SPX",
        action=Action.BUY,
        entry=4000,
        stop_loss=3900,
        size=1,
        atr=20,
        use_trailing_stop=True,
        confidence="high",
        reasoning="Breakout",
        entry_type=EntryType.BREAKOUT,
    )

    # 2. Mock Adapters
    mock_ig = AsyncMock()
    mock_ig.get_account_balance = AsyncMock(return_value=10000.0)
    mock_ig.fetch_market_details.return_value = {
        "snapshot": {"bid": 3990, "offer": 3995}
    }

    # Mock VIX Search for Analyzer
    mock_ig.search_markets.return_value = {"markets": [{"epic": "VIX_EPIC"}]}
    mock_ig.fetch_open_positions.return_value = {"positions": []}

    # Mock Candles to pass _build_market_regime
    def make_candle(price, time_offset_min=0):
        t = datetime.now() - timedelta(minutes=time_offset_min)
        return {
            "snapshotTime": t.strftime("%Y/%m/%d %H:%M:%S"),
            "openPrice": {"bid": price, "ask": price},
            "highPrice": {"bid": price + 10, "ask": price + 10},
            "lowPrice": {"bid": price - 10, "ask": price - 10},
            "closePrice": {"bid": price + 5, "ask": price + 5},
            "lastTradedVolume": 100,
        }

    prices_data = {"prices": [make_candle(4000, i * 15) for i in range(50)]}

    mock_ig.fetch_historical_prices = AsyncMock(return_value=prices_data)
    mock_ig.fetch_client_sentiment_by_instrument = AsyncMock(
        return_value={"longPositionPercentage": 50}
    )
    mock_ig.create_order = AsyncMock(return_value={"dealReference": "REF123", "level": 4000.0})
    mock_ig.fetch_deal_confirmation = AsyncMock(return_value={"dealStatus": "ACCEPTED", "dealId": "DEAL123"})

    mock_gemini = AsyncMock()
    mock_gemini.analyze_market.side_effect = [wait_signal, buy_signal]

    mock_streamer = MagicMock()
    mock_streamer.stop = AsyncMock()

    # Stream for execution
    async def mock_stream(epic):
        yield {"type": "price_update", "bid": 4000, "offer": 4001}

    mock_streamer.stream = mock_stream

    mock_status = MagicMock()
    mock_status.is_holiday.return_value = False

    # Mock News to avoid external calls
    mock_news = MagicMock()
    mock_news.fetch_news = AsyncMock(return_value="Market is volatile.")

    # 3. Patching
    with (
        patch("app.core.container.GeminiService", return_value=mock_gemini),
        patch("app.core.container.StreamerService", return_value=mock_streamer),
        patch("app.core.container.MarketStatusService", return_value=mock_status),
        patch("app.core.container.NewsClient", return_value=mock_news),
        patch("app.cli.trade.AsyncIGClient.get_instance") as mock_get_instance,
    ):
        with patch("app.cli.trade.asyncio.sleep", AsyncMock()) as mock_sleep:
            mock_get_instance.return_value.__aenter__.return_value = mock_ig

            # 4. Run
            await run_market_strategy("spx", dry_run=False, yes=True)

            # 5. Assertions
            assert mock_ig.fetch_historical_prices.call_count > 0, (
                "No historical data fetched"
            )
            assert mock_gemini.analyze_market.call_count == 2
            assert mock_sleep.call_count >= 1
            mock_ig.create_order.assert_called_once()

            args, kwargs = mock_ig.create_order.call_args
            assert kwargs["direction"] == "BUY"
            # In Container, spx -> IX.D.SPTRD.DAILY.IP
            assert kwargs["epic"] == "IX.D.SPTRD.DAILY.IP"

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from app.services.trader import StrategyEngine
from app.domain.models import MarketRegime, VolatilityRegime, TrendContext
from app.adapters.gemini_service import TradingSignal, Action


@pytest.fixture
def mock_deps():
    mock_ig = MagicMock()
    mock_ig.create_order = AsyncMock(return_value={"dealId": "TEST_DEAL"})

    mock_data = MagicMock()
    mock_analyst = MagicMock()
    mock_news = MagicMock()
    mock_news.fetch_news = AsyncMock(return_value="News")
    mock_streamer = MagicMock()

    return mock_ig, mock_data, mock_analyst, mock_news, mock_streamer


@pytest.fixture
def dummy_regime():
    return MarketRegime(
        symbol="FTSE100",
        timestamp=datetime.now(timezone.utc),
        current_price=7000,
        daily_open=6900,
        prev_close=6950,
        atr_14=15,
        avg_atr=15,
        volatility_ratio=1.0,
        regime=VolatilityRegime.MEDIUM,
        ema_20=6980,
        trend=TrendContext.BULLISH,
        rsi_14=60,
        gap_percent=0.5,
    )


@pytest.mark.asyncio
async def test_strategy_engine_run_buy(mock_deps, dummy_regime, monkeypatch):
    mock_ig, mock_data, mock_analyst, mock_news, mock_streamer = mock_deps

    # Mock stream to trigger BUY at 7000
    async def trigger_stream(epic):
        yield {
            "type": "price_update",
            "bid": 6990,
            "offer": 7005,
        }  # Trigger! (Offer >= 7000)

    mock_streamer.stream = trigger_stream

    mock_analyst.analyze_market = AsyncMock(
        return_value=TradingSignal(
            ticker="FTSE100",
            action=Action.BUY,
            entry=7000,
            stop_loss=6950,
            size=1,
            atr=10,
            use_trailing_stop=True,
            confidence="high",
            reasoning="Go",
        )
    )

    engine = StrategyEngine(
        mock_ig, mock_data, mock_analyst, mock_news, mock_streamer, dry_run=False
    )

    # Mock data fetching using monkeypatch
    mock_build = AsyncMock(return_value=dummy_regime)
    monkeypatch.setattr(engine, "_build_market_regime", mock_build)

    await engine.run_strategy("london")

    mock_ig.create_order.assert_called_once()
    assert mock_ig.create_order.call_args.kwargs["direction"] == "BUY"


@pytest.mark.asyncio
async def test_strategy_engine_wait_action(mock_deps, dummy_regime, monkeypatch):
    mock_ig, mock_data, mock_analyst, mock_news, mock_streamer = mock_deps

    mock_analyst.analyze_market = AsyncMock(
        return_value=TradingSignal(
            ticker="FTSE100",
            action=Action.WAIT,
            entry=0,
            stop_loss=0,
            size=0,
            atr=0,
            use_trailing_stop=False,
            confidence="low",
            reasoning="Wait",
        )
    )

    engine = StrategyEngine(
        mock_ig, mock_data, mock_analyst, mock_news, mock_streamer, dry_run=False
    )

    mock_build = AsyncMock(return_value=dummy_regime)
    monkeypatch.setattr(engine, "_build_market_regime", mock_build)

    await engine.run_strategy("london")

    # Should NOT place order
    mock_ig.create_order.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_engine_dry_run(mock_deps, dummy_regime, monkeypatch):
    mock_ig, mock_data, mock_analyst, mock_news, mock_streamer = mock_deps

    mock_analyst.analyze_market = AsyncMock(
        return_value=TradingSignal(
            ticker="FTSE100",
            action=Action.SELL,
            entry=7000,
            stop_loss=7050,
            size=1,
            atr=10,
            use_trailing_stop=True,
            confidence="high",
            reasoning="Sell",
        )
    )

    # Dry Run = True
    engine = StrategyEngine(
        mock_ig, mock_data, mock_analyst, mock_news, mock_streamer, dry_run=True
    )

    mock_build = AsyncMock(return_value=dummy_regime)
    monkeypatch.setattr(engine, "_build_market_regime", mock_build)

    await engine.run_strategy("london")

    # Should NOT call create_order despite SELL signal
    mock_ig.create_order.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_engine_insufficient_data(mock_deps, monkeypatch):
    mock_ig, mock_data, mock_analyst, mock_news, mock_streamer = mock_deps

    engine = StrategyEngine(mock_ig, mock_data, mock_analyst, mock_news, mock_streamer)

    # Simulate data failure
    mock_build = AsyncMock(return_value=None)
    monkeypatch.setattr(engine, "_build_market_regime", mock_build)

    await engine.run_strategy("london")

    mock_analyst.analyze_market.assert_not_called()
    mock_ig.create_order.assert_not_called()

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
async def test_strategy_engine_analyst_mode(mock_deps, dummy_regime, monkeypatch):
    mock_ig, mock_data, mock_analyst, mock_news, mock_streamer = mock_deps

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

    # Analyst Mode = True
    engine = StrategyEngine(
        mock_ig, mock_data, mock_analyst, mock_news, mock_streamer, analyst_mode=True
    )

    mock_build = AsyncMock(return_value=dummy_regime)
    monkeypatch.setattr(engine, "_build_market_regime", mock_build)

    await engine.run_strategy("london")

    # Should NOT call create_order even with BUY signal
    mock_ig.create_order.assert_not_called()

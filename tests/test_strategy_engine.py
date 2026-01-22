import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from app.services.trader import StrategyEngine
from app.domain.models import MarketRegime, VolatilityRegime, TrendContext
from app.adapters.gemini_service import TradingSignal, Action


@pytest.mark.asyncio
async def test_strategy_engine_run():
    # Mocks
    mock_ig = MagicMock()
    mock_ig.create_order = AsyncMock(return_value={"dealId": "TEST_DEAL"})

    mock_data = MagicMock()
    # Mock candle data or _build_market_regime directly
    # Easier to mock _build_market_regime for high level test

    mock_analyst = MagicMock()
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
            reasoning="Test",
        )
    )

    engine = StrategyEngine(mock_ig, mock_data, mock_analyst, dry_run=False)

    # Mock the internal method to skip data fetching logic in this unit test
    engine._build_market_regime = AsyncMock(  # type: ignore
        return_value=MarketRegime(
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
    )

    # Run
    await engine.run_strategy("london")

    # Verify
    mock_analyst.analyze_market.assert_called_once()
    mock_ig.create_order.assert_called_once()

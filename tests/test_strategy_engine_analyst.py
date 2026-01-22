import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.trader import StrategyEngine
from app.adapters.gemini_service import TradingSignal, Action


@pytest.fixture
def mock_deps():
    mock_analyzer = MagicMock()
    mock_risk = MagicMock()
    mock_executor = MagicMock()
    return mock_analyzer, mock_risk, mock_executor


@pytest.mark.asyncio
async def test_strategy_engine_analyst_mode(mock_deps, monkeypatch):
    mock_analyzer, mock_risk, mock_executor = mock_deps

    mock_signal = TradingSignal(
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

    mock_analyzer.analyze_market = AsyncMock(return_value=mock_signal)
    mock_save = AsyncMock(return_value=MagicMock(id=123))

    # Analyst Mode = True
    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor, analyst_mode=True)
    monkeypatch.setattr(engine, "_save_signal", mock_save)

    await engine.run_strategy("london")

    # Should analyze
    mock_analyzer.analyze_market.assert_called_once()

    # Should NOT validate or execute
    mock_risk.validate_signal.assert_not_called()
    mock_executor.execute_trade.assert_not_called()

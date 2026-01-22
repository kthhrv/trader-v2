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
async def test_strategy_engine_run_buy(mock_deps, monkeypatch):
    mock_analyzer, mock_risk, mock_executor = mock_deps

    # 1. Analyze
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
    mock_db_signal = MagicMock(id=123)

    mock_analyzer.analyze_market = AsyncMock(return_value=mock_signal)
    mock_risk.validate_signal = AsyncMock(return_value=True)
    mock_executor.execute_trade = AsyncMock()

    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor)

    mock_save = AsyncMock(return_value=mock_db_signal)
    monkeypatch.setattr(engine, "_save_signal", mock_save)

    await engine.run_strategy("london")

    mock_analyzer.analyze_market.assert_called_once()
    mock_risk.validate_signal.assert_called_once()
    mock_executor.execute_trade.assert_called_once()
    assert mock_executor.execute_trade.call_args[0][0] == mock_signal


@pytest.mark.asyncio
async def test_strategy_engine_wait_action(mock_deps, monkeypatch):
    mock_analyzer, mock_risk, mock_executor = mock_deps

    mock_signal = TradingSignal(
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
    mock_analyzer.analyze_market = AsyncMock(return_value=mock_signal)
    mock_save = AsyncMock(return_value=MagicMock(id=123))

    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor)
    monkeypatch.setattr(engine, "_save_signal", mock_save)

    await engine.run_strategy("london")

    mock_executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_engine_dry_run(mock_deps):
    pass


@pytest.mark.asyncio
async def test_strategy_engine_validation_fail(mock_deps, monkeypatch):
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
    mock_risk.validate_signal = AsyncMock(return_value=False)  # Fail
    mock_save = AsyncMock(return_value=MagicMock(id=123))

    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor)
    monkeypatch.setattr(engine, "_save_signal", mock_save)

    await engine.run_strategy("london")

    mock_risk.validate_signal.assert_called_once()
    mock_executor.execute_trade.assert_not_called()

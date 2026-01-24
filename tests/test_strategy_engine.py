import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.trader import StrategyEngine
from app.adapters.gemini_service import TradingSignal, Action


@pytest.fixture
def mock_deps():
    mock_analyzer = MagicMock()
    mock_risk = MagicMock()
    mock_executor = MagicMock()
    mock_status = MagicMock()
    return mock_analyzer, mock_risk, mock_executor, mock_status


@pytest.mark.asyncio
async def test_strategy_engine_run_buy(mock_deps, monkeypatch):
    mock_analyzer, mock_risk, mock_executor, mock_status = mock_deps
    mock_status.is_holiday.return_value = False

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

    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor, mock_status)

    mock_save = AsyncMock(return_value=mock_db_signal)
    monkeypatch.setattr(engine, "_save_signal", mock_save)

    await engine.run_strategy("ftse")

    mock_analyzer.analyze_market.assert_called_once()
    mock_risk.validate_signal.assert_called_once_with(mock_signal)
    mock_executor.execute_trade.assert_called_once()
    assert mock_executor.execute_trade.call_args[0][0] == mock_signal
    assert mock_executor.execute_trade.call_args[0][3] == 2.0  # max_spread for ftse


@pytest.mark.asyncio
async def test_strategy_engine_confirmation_callback(mock_deps, monkeypatch):
    """
    Verifies that the engine respects the return value of the confirmation callback.
    """
    mock_analyzer, mock_risk, mock_executor, mock_status = mock_deps
    mock_status.is_holiday.return_value = False

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
    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor, mock_status)
    monkeypatch.setattr(engine, "_save_signal", AsyncMock(return_value=MagicMock(id=1)))

    # 1. Test Callback returns False (User cancels)
    mock_cb_false = MagicMock(return_value=False)
    result = await engine.run_strategy("ftse", confirmation_callback=mock_cb_false)

    assert result == "SKIPPED"  # StrategyResult.SKIPPED
    mock_cb_false.assert_called_once()
    mock_executor.execute_trade.assert_not_called()

    # 2. Test Callback returns True (User accepts)
    mock_risk.validate_signal = AsyncMock(return_value=True)
    mock_executor.execute_trade = AsyncMock()
    mock_cb_true = MagicMock(return_value=True)
    result_true = await engine.run_strategy("ftse", confirmation_callback=mock_cb_true)

    assert result_true == "EXECUTED"  # StrategyResult.EXECUTED
    mock_cb_true.assert_called_once()
    mock_executor.execute_trade.assert_called_once()


@pytest.mark.asyncio
async def test_strategy_engine_wait_action(mock_deps, monkeypatch):
    mock_analyzer, mock_risk, mock_executor, mock_status = mock_deps
    mock_status.is_holiday.return_value = False

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

    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor, mock_status)
    monkeypatch.setattr(engine, "_save_signal", mock_save)

    await engine.run_strategy("ftse")

    mock_executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_engine_dry_run(mock_deps):
    pass


@pytest.mark.asyncio
async def test_strategy_engine_validation_fail(mock_deps, monkeypatch):
    mock_analyzer, mock_risk, mock_executor, mock_status = mock_deps
    mock_status.is_holiday.return_value = False

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

    engine = StrategyEngine(mock_analyzer, mock_risk, mock_executor, mock_status)
    monkeypatch.setattr(engine, "_save_signal", mock_save)

    await engine.run_strategy("ftse")

    mock_risk.validate_signal.assert_called_once_with(mock_signal)
    mock_executor.execute_trade.assert_not_called()

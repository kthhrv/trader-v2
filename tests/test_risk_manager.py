import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.risk import RiskManager
from app.adapters.gemini_service import TradingSignal, Action
from app.core.config import settings


@pytest.fixture
def mock_ig_client():
    client = MagicMock()
    # Default balance 10,000
    client.get_account_balance = AsyncMock(return_value=10000.0)
    return client


@pytest.fixture
def risk_manager(mock_ig_client):
    return RiskManager(mock_ig_client)


@pytest.fixture
def base_signal():
    return TradingSignal(
        ticker="TEST.EPIC",
        action=Action.BUY,
        entry=100.0,
        stop_loss=90.0,  # Distance 10
        size=1.0,  # Default AI size
        atr=5.0,
        use_trailing_stop=False,
        confidence="high",
        reasoning="Test",
    )


@pytest.mark.asyncio
async def test_dynamic_sizing_standard(risk_manager, base_signal):
    """
    Test standard 1% risk calculation.
    Balance: 10,000
    Risk%: 0.01 (100)
    Distance: 10
    Expected Size: 100 / 10 = 10.0
    """
    # Ensure config defaults
    settings.RISK_PER_TRADE_PERCENT = 0.01
    settings.MIN_ACCOUNT_BALANCE = 0.0

    valid = await risk_manager.validate_signal(base_signal)

    assert valid is True
    assert base_signal.size == 10.0


@pytest.mark.asyncio
async def test_dynamic_sizing_minimum_violation(risk_manager, base_signal):
    """
    Test rejection if calculated size is too small (< 0.5).
    Balance: 100
    Risk%: 0.01 (1)
    Distance: 10
    Expected Size: 1 / 10 = 0.1 -> Reject
    """
    risk_manager.ig_client.get_account_balance.return_value = 100.0

    valid = await risk_manager.validate_signal(base_signal)

    assert valid is False


@pytest.mark.asyncio
async def test_dynamic_sizing_floor_protection(risk_manager, base_signal):
    """
    Test capping risk if balance is near floor.
    Balance: 10,000
    Floor: 9,950
    Allowed Loss: 50 (Less than standard 1% = 100)
    Distance: 10
    Expected Size: 50 / 10 = 5.0
    """
    settings.MIN_ACCOUNT_BALANCE = 9950.0

    valid = await risk_manager.validate_signal(base_signal)

    assert valid is True
    assert base_signal.size == 5.0


@pytest.mark.asyncio
async def test_validate_signal_fetch_balance_failure(risk_manager, base_signal):
    """
    Test fail-safe if balance fetch fails.
    """
    risk_manager.ig_client.get_account_balance.side_effect = Exception("API Error")

    valid = await risk_manager.validate_signal(base_signal)

    assert valid is False


@pytest.mark.asyncio
async def test_validate_signal_zero_distance(risk_manager, base_signal):
    """
    Test rejection if stop loss equals entry (distance 0).
    """
    base_signal.stop_loss = 100.0  # Same as entry

    valid = await risk_manager.validate_signal(base_signal)

    assert valid is False

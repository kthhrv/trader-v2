import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.trader import StrategyEngine
from app.services.market_status import MarketStatusService
from app.core.markets import MARKET_CONFIGS


@pytest.fixture
def mock_deps():
    return {
        "analyzer": AsyncMock(),
        "risk_manager": AsyncMock(),
        "executor": AsyncMock(),
        "market_status": MagicMock(spec=MarketStatusService),
    }


@pytest.mark.asyncio
async def test_holiday_block(mock_deps):
    """
    Test that run_strategy aborts early if is_holiday returns True.
    """
    market_key = "ftse"
    epic = MARKET_CONFIGS[market_key]["epic"]

    # Setup Mock
    mock_deps["market_status"].is_holiday.return_value = True

    engine = StrategyEngine(
        analyzer=mock_deps["analyzer"],
        risk_manager=mock_deps["risk_manager"],
        executor=mock_deps["executor"],
        market_status=mock_deps["market_status"],
    )

    await engine.run_strategy(market_key)

    # Verification
    mock_deps["market_status"].is_holiday.assert_called_with(epic)
    mock_deps["analyzer"].analyze_market.assert_not_called()


@pytest.mark.asyncio
async def test_no_holiday_proceeds(mock_deps):
    """
    Test that run_strategy proceeds if is_holiday returns False.
    """
    market_key = "ftse"

    # Setup Mock
    mock_deps["market_status"].is_holiday.return_value = False
    mock_deps["analyzer"].analyze_market.return_value = None  # Stop execution here

    engine = StrategyEngine(
        analyzer=mock_deps["analyzer"],
        risk_manager=mock_deps["risk_manager"],
        executor=mock_deps["executor"],
        market_status=mock_deps["market_status"],
    )

    await engine.run_strategy(market_key)

    # Verification
    mock_deps["analyzer"].analyze_market.assert_called_once()


def test_market_status_init_real():
    """
    Verify that MarketStatusService initializes correctly with real holiday calendars.
    Matches logic in V1's test_market_status.py.
    """
    service = MarketStatusService()
    assert service.uk_holidays is not None
    assert service.us_holidays is not None
    assert service.jp_holidays is not None

    # Check a known holiday
    from datetime import date

    christmas = date(2025, 12, 25)
    assert christmas in service.uk_holidays

from unittest.mock import MagicMock
from app.core.container import Container
from app.services.trader import StrategyEngine
from app.services.analyzer import MarketAnalyzer
from app.services.executor import TradeExecutor


def test_container_creates_strategy_engine():
    """
    Verifies that the Container can correctly assemble the StrategyEngine stack.
    """
    mock_client = MagicMock()

    engine = Container.create_strategy_engine(
        ig_client=mock_client, dry_run=True, analyst_mode=False, yes_mode=True
    )

    assert isinstance(engine, StrategyEngine)
    assert isinstance(engine.analyzer, MarketAnalyzer)
    assert isinstance(engine.executor, TradeExecutor)
    assert engine.yes_mode is True
    assert engine.executor.dry_run is True

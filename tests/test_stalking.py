import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from app.cli.trade import run_market_strategy
from app.services.trader import StrategyResult


@pytest.mark.asyncio
async def test_run_market_strategy_stalking_loop():
    """
    Tests that run_market_strategy loops correctly when receiving WAIT
    and stops when receiving EXECUTED.
    """
    market_key = "spx"

    mock_engine = MagicMock()
    mock_engine.run_strategy = AsyncMock(
        side_effect=[StrategyResult.WAIT, StrategyResult.WAIT, StrategyResult.EXECUTED]
    )
    # The engine exposes an executor attribute which has a streamer
    mock_engine.executor.streamer.stop = AsyncMock()

    mock_config = {
        "epic": "IX.D.SPTRD.DAILY.IP",
        "stalking": {"enabled": True, "duration_minutes": 10, "interval_minutes": 0.01},
        "max_spread": 1.6,
    }

    # Patch Container to return our mock engine
    with patch("app.cli.trade.MARKET_CONFIGS", {market_key: mock_config}):
        with patch("app.cli.trade.Container") as mock_container:
            mock_container.create_strategy_engine.return_value = mock_engine

            with patch("app.cli.trade.AsyncIGClient.get_instance"):
                with patch("app.cli.trade.asyncio.sleep", AsyncMock()) as mock_sleep:
                    await run_market_strategy(market_key, dry_run=True, yes=True)

                    assert mock_engine.run_strategy.call_count == 3
                    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_run_market_strategy_stalking_timeout():
    """
    Tests that the stalking loop exits if duration expires.
    """
    market_key = "spx"

    mock_engine = MagicMock()
    mock_engine.run_strategy = AsyncMock(return_value=StrategyResult.WAIT)
    mock_engine.executor.streamer.stop = AsyncMock()

    mock_config = {
        "epic": "IX.D.SPTRD.DAILY.IP",
        "stalking": {"enabled": True, "duration_minutes": 1, "interval_minutes": 1},
        "max_spread": 1.6,
    }

    start_time = datetime.now()

    with patch("app.cli.trade.MARKET_CONFIGS", {market_key: mock_config}):
        with patch("app.cli.trade.Container") as mock_container:
            mock_container.create_strategy_engine.return_value = mock_engine

            with patch("app.cli.trade.AsyncIGClient.get_instance"):
                with patch("app.cli.trade.asyncio.sleep", AsyncMock()):
                    with patch("app.cli.trade.datetime") as mock_datetime:
                        mock_datetime.now.side_effect = [
                            start_time,
                            start_time + timedelta(seconds=30),
                            start_time + timedelta(minutes=2),
                        ]

                        await run_market_strategy(market_key, dry_run=True, yes=True)

                        assert mock_engine.run_strategy.call_count == 2

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
    market_key = "spx"  # SPX has stalking enabled in our config

    # 1. Mock the StrategyEngine
    # We want it to return [WAIT, WAIT, EXECUTED]
    mock_engine = MagicMock()
    mock_engine.run_strategy = AsyncMock(
        side_effect=[StrategyResult.WAIT, StrategyResult.WAIT, StrategyResult.EXECUTED]
    )

    # 2. Mock the configuration to ensure stalking is short for the test
    mock_config = {
        "epic": "IX.D.SPTRD.DAILY.IP",
        "stalking": {
            "enabled": True,
            "duration_minutes": 10,
            "interval_minutes": 0.01,
        },  # Very fast interval
        "max_spread": 1.6,
    }

    # Mock Streamer
    mock_streamer = MagicMock()
    mock_streamer.stop = AsyncMock()

    # 3. Patch dependencies
    with patch("app.cli.trade.MARKET_CONFIGS", {market_key: mock_config}):
        with patch("app.cli.trade.StrategyEngine", return_value=mock_engine):
            with patch("app.cli.trade.AsyncIGClient.get_instance"):
                with patch("app.cli.trade.CollectorService"):
                    with patch("app.cli.trade.MarketDataService"):
                        with patch("app.cli.trade.GeminiService"):
                            with patch("app.cli.trade.NewsClient"):
                                with patch(
                                    "app.cli.trade.StreamerService",
                                    return_value=mock_streamer,
                                ):
                                    with patch("app.cli.trade.RiskManager"):
                                        with patch("app.cli.trade.MarketAnalyzer"):
                                            with patch(
                                                "app.cli.trade.MarketStatusService"
                                            ):
                                                with patch(
                                                    "app.cli.trade.TradeExecutor"
                                                ):
                                                    with patch(
                                                        "app.cli.trade.asyncio.sleep",
                                                        AsyncMock(),
                                                    ) as mock_sleep:
                                                        # Run the strategy
                                                        await run_market_strategy(
                                                            market_key,
                                                            dry_run=True,
                                                            yes=True,
                                                        )

                                                        # 4. Assertions
                                                        # Should have called run_strategy 3 times
                                                        assert (
                                                            mock_engine.run_strategy.call_count
                                                            == 3
                                                        )
                                                        # Should have slept 2 times
                                                        assert (
                                                            mock_sleep.call_count == 2
                                                        )


@pytest.mark.asyncio
async def test_run_market_strategy_stalking_timeout():
    """
    Tests that the stalking loop exits if duration expires.
    """
    market_key = "spx"

    mock_engine = MagicMock()
    # Always return WAIT
    mock_engine.run_strategy = AsyncMock(return_value=StrategyResult.WAIT)

    # Duration 1 min, Interval 1 min.
    # Mocking datetime to simulate passage of time.
    mock_config = {
        "epic": "IX.D.SPTRD.DAILY.IP",
        "stalking": {"enabled": True, "duration_minutes": 1, "interval_minutes": 1},
        "max_spread": 1.6,
    }

    # Mock Streamer
    mock_streamer = MagicMock()
    mock_streamer.stop = AsyncMock()

    start_time = datetime.now()
    # Mocking datetime.now() calls:
    # 1. start_time = datetime.now() (T=0)
    # 2. engine.run_strategy()
    # 3. elapsed = (datetime.now() - start_time) (T=0.5 -> ok)
    # 4. asyncio.sleep()
    # 5. engine.run_strategy()
    # 6. elapsed = (datetime.now() - start_time) (T=2 -> timeout)
    with patch("app.cli.trade.MARKET_CONFIGS", {market_key: mock_config}):
        with patch("app.cli.trade.StrategyEngine", return_value=mock_engine):
            with patch("app.cli.trade.AsyncIGClient.get_instance"):
                with patch("app.cli.trade.CollectorService"):
                    with patch("app.cli.trade.MarketDataService"):
                        with patch("app.cli.trade.GeminiService"):
                            with patch("app.cli.trade.NewsClient"):
                                with patch(
                                    "app.cli.trade.StreamerService",
                                    return_value=mock_streamer,
                                ):
                                    with patch("app.cli.trade.RiskManager"):
                                        with patch("app.cli.trade.MarketAnalyzer"):
                                            with patch(
                                                "app.cli.trade.MarketStatusService"
                                            ):
                                                with patch(
                                                    "app.cli.trade.TradeExecutor"
                                                ):
                                                    with patch(
                                                        "app.cli.trade.asyncio.sleep",
                                                        AsyncMock(),
                                                    ):
                                                        with patch(
                                                            "app.cli.trade.datetime"
                                                        ) as mock_datetime:
                                                            mock_datetime.now.side_effect = [
                                                                start_time,  # initial
                                                                start_time
                                                                + timedelta(
                                                                    seconds=30
                                                                ),  # first check
                                                                start_time
                                                                + timedelta(
                                                                    minutes=2
                                                                ),  # second check (timeout)
                                                            ]

                                                            await run_market_strategy(
                                                                market_key,
                                                                dry_run=True,
                                                                yes=True,
                                                            )

                                                            # Should have called run_strategy twice
                                                            assert (
                                                                mock_engine.run_strategy.call_count
                                                                == 2
                                                            )

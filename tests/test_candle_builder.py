import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from app.streamer.candle_builder import CandleBuilder


@pytest.mark.asyncio
async def test_candle_builder_aggregation():
    """
    Tests that ticks are correctly aggregated into 1m, 5m, and 15m candles.
    """
    builder = CandleBuilder()
    epic = "TEST.EPIC"

    # Mock DB session
    with patch("app.streamer.candle_builder.async_session_maker") as mock_session_maker:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()  # session.add is synchronous
        mock_session_maker.return_value.__aenter__.return_value = mock_session

        # 1. First Tick (Initialization)
        t1 = datetime(2023, 1, 1, 10, 0, 1, tzinfo=timezone.utc)
        with patch("app.streamer.candle_builder.datetime") as mock_dt:
            mock_dt.now.return_value = t1
            await builder.on_tick(epic, 100.0)

        assert epic in builder.state
        assert builder.state[epic]["MINUTE"]["open"] == 100.0
        assert builder.state[epic]["MINUTE_5"]["open"] == 100.0

        # 2. Second Tick (Update same buckets)
        t2 = datetime(2023, 1, 1, 10, 0, 30, tzinfo=timezone.utc)
        with patch("app.streamer.candle_builder.datetime") as mock_dt:
            mock_dt.now.return_value = t2
            await builder.on_tick(epic, 105.0)

        assert builder.state[epic]["MINUTE"]["high"] == 105.0
        assert builder.state[epic]["MINUTE"]["volume"] == 2

        # 3. Third Tick (New 1m bucket, should flush old 1m)
        t3 = datetime(2023, 1, 1, 10, 1, 5, tzinfo=timezone.utc)
        with patch("app.streamer.candle_builder.datetime") as mock_dt:
            mock_dt.now.return_value = t3
            await builder.on_tick(epic, 110.0)

        # Check if save was called for 1m candle (from 10:00)
        assert mock_session.add.called
        saved_candle = mock_session.add.call_args[0][0]
        assert saved_candle.resolution == "MINUTE"
        assert saved_candle.timestamp == datetime(
            2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc
        )
        assert saved_candle.close == 105.0

        # Reset mock
        mock_session.add.reset_mock()

        # 4. Fourth Tick (New 5m bucket, should flush old 5m)
        t4 = datetime(2023, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
        with patch("app.streamer.candle_builder.datetime") as mock_dt:
            mock_dt.now.return_value = t4
            await builder.on_tick(epic, 120.0)

        # Should have flushed the 10:01 1m candle AND the 10:00 5m candle
        assert mock_session.add.call_count >= 2
        resolutions = [
            call[0][0].resolution for call in mock_session.add.call_args_list
        ]
        assert "MINUTE_5" in resolutions
        assert "MINUTE" in resolutions

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from app.streamer.candle_builder import CandleBuilder


@pytest.mark.asyncio
async def test_candle_builder_aggregation():
    """
    Tests that ticks are correctly aggregated into 1m, 5m, and 15m candles.
    """
    mock_redis = AsyncMock()
    builder = CandleBuilder(mock_redis)
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
        assert mock_session.execute.called
        # Verify it published to Redis
        mock_redis.publish.assert_called()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "market_candles"
        payload = json.loads(args[1])
        assert payload["event"] == "candle_closed"

        # Reset mock
        mock_session.execute.reset_mock()

        # 4. Fourth Tick (New 5m bucket, should flush old 5m)
        t4 = datetime(2023, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
        with patch("app.streamer.candle_builder.datetime") as mock_dt:
            mock_dt.now.return_value = t4
            await builder.on_tick(epic, 120.0)

        # Should have flushed the 10:01 1m candle AND the 10:00 5m candle
        assert mock_session.execute.call_count >= 2

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from app.services.executor import TradeExecutor
from app.adapters.gemini_service import EntryType


@pytest.mark.asyncio
async def test_wait_for_trigger_timeout():
    mock_client = AsyncMock()
    mock_streamer = MagicMock()
    mock_status = MagicMock()

    # Setup Streamer to yield nothing initially (wait)
    # Then yield a tick after timeout?
    # No, we just need to verify it returns None if time passes.

    executor = TradeExecutor(mock_client, mock_streamer, mock_status)

    # We yield some ticks to keep the loop running
    async def mock_stream(epic):
        yield {"type": "price_update", "bid": 100, "offer": 101}
        yield {"type": "price_update", "bid": 100, "offer": 101}
        yield {"type": "price_update", "bid": 100, "offer": 101}

    mock_streamer.stream = mock_stream

    start_ts = datetime.now(timezone.utc).timestamp()

    # Mock datetime to simulate passage of time > timeout
    with patch("app.services.executor.datetime") as mock_dt:
        mock_dt.now.return_value.timestamp.side_effect = [
            start_ts,  # Start time
            start_ts + 5.0,  # Loop 1 (5s elapsed)
            start_ts + 65.0,  # Loop 2 (65s elapsed) -> Should Timeout if limit is 60s
        ]
        mock_dt.now.return_value.tzinfo = timezone.utc

        result = await executor._wait_for_trigger(
            epic="TEST",
            direction="BUY",
            target_entry=105.0,  # Price never hit (current 101)
            entry_type=EntryType.BREAKOUT,
            max_spread=5.0,
            timeout_seconds=60,  # Short timeout
        )

        assert result is None

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from app.services.executor import TradeExecutor


@pytest.fixture
def mock_deps():
    mock_client = AsyncMock()
    mock_streamer = MagicMock()
    # Mock stop method for streamer
    mock_streamer.stop = AsyncMock()
    mock_status = MagicMock()
    return mock_client, mock_streamer, mock_status


@pytest.mark.asyncio
async def test_executor_breakeven_trigger(mock_deps):
    mock_client, mock_streamer, mock_status = mock_deps

    # Setup: Entry 100, Stop 90 (Risk 10). BE Trigger 1.5R = 15pts = Price 115.
    entry_price = 100.0
    initial_stop = 90.0
    atr = 5.0

    async def mock_stream(epic):
        # 1. Price moves slightly up (110). Profit 10 < 15. No Action.
        yield {"type": "price_update", "bid": 110.0, "offer": 112.0}
        # 2. Price hits trigger (116). Profit 16 > 15. Move to BE (100).
        # AND Trail Logic: 116 - 15 = 101. 101 > 100 + 0.5. Move to 101.
        yield {"type": "price_update", "bid": 116.0, "offer": 118.0}

    mock_streamer.stream = mock_stream
    mock_status.get_market_close_datetime.return_value = datetime.now(
        timezone.utc
    ) + timedelta(hours=5)

    executor = TradeExecutor(mock_client, mock_streamer, mock_status)
    executor._update_execution_stop = cast(Any, AsyncMock())
    executor._is_position_open = cast(Any, AsyncMock(return_value=True))

    import itertools

    ts = datetime.now(timezone.utc).timestamp()
    with patch("app.services.executor.datetime") as mock_dt:
        mock_dt.now.return_value.timestamp.side_effect = itertools.count(ts, 10.0)
        mock_dt.now.return_value.tzinfo = timezone.utc

        await executor._monitor_position(
            deal_id="DEAL123",
            epic="TEST",
            direction="BUY",
            entry_price=entry_price,
            current_stop=initial_stop,
            atr=atr,
            size=1.0,
        )

    # Verify Update called at least once
    assert mock_client.update_open_position.call_count >= 1

    # Verify the sequence includes BE (100.0) or better
    # Note: If it happened in the same tick, we might see 100.0 then 101.0
    # or just 101.0 if the actor combined them.
    calls = mock_client.update_open_position.call_args_list
    # Check if ANY call set stop to >= 100.0 (for BUY, higher is better)
    has_be_or_better = any(call.kwargs.get("stop_level") >= 100.0 for call in calls)
    assert has_be_or_better, f"Breakeven or better update not found in calls: {calls}"


@pytest.mark.asyncio
async def test_executor_trailing_stop(mock_deps):
    mock_client, mock_streamer, mock_status = mock_deps

    async def mock_stream(epic):
        yield {"type": "price_update", "bid": 120.0, "offer": 122.0}

    mock_streamer.stream = mock_stream
    mock_status.get_market_close_datetime.return_value = datetime.now(
        timezone.utc
    ) + timedelta(hours=5)

    executor = TradeExecutor(mock_client, mock_streamer, mock_status)
    executor._update_execution_stop = cast(Any, AsyncMock())
    executor._is_position_open = cast(Any, AsyncMock(return_value=True))

    with patch("app.services.executor.datetime") as mock_dt:
        import itertools

        ts = datetime.now(timezone.utc).timestamp()
        mock_dt.now.return_value.timestamp.side_effect = itertools.count(ts, 10.0)
        mock_dt.now.return_value.tzinfo = timezone.utc

        await executor._monitor_position(
            deal_id="DEAL123",
            epic="TEST",
            direction="BUY",
            entry_price=100.0,
            current_stop=90.0,
            atr=5.0,
            size=1.0,
        )

    # Verify calls
    assert mock_client.update_open_position.call_count >= 1
    # Last call should be 105.0 (120 - 15)
    args, kwargs = mock_client.update_open_position.call_args
    assert kwargs["stop_level"] == 105.0


@pytest.mark.asyncio
async def test_executor_force_close_at_market_close(mock_deps):
    mock_client, mock_streamer, mock_status = mock_deps

    # Setup: 5 mins before close
    # We construct 'now' to be close_time - 5mins
    # And 'close_time' to be some fixed future time
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    close_time = base_time + timedelta(minutes=5)

    mock_status.get_market_close_datetime.return_value = close_time

    # Stream: just needs to yield something to keep loop alive
    async def mock_stream(epic):
        yield {"type": "price_update", "bid": 100, "offer": 101}
        yield {"type": "price_update", "bid": 100, "offer": 101}

    mock_streamer.stream = mock_stream

    executor = TradeExecutor(mock_client, mock_streamer, mock_status)
    executor._sync_outcome = cast(Any, AsyncMock())
    executor._is_position_open = cast(Any, AsyncMock(return_value=True))

    with patch("app.services.executor.datetime") as mock_dt:
        # Mock datetime.now() to return sequence of times
        # 1. Start Time (base_time)
        # 2. Loop Check 1 (base_time + 70s) -> >60s triggers liveness/close check
        mock_dt.now.side_effect = [
            base_time,
            base_time + timedelta(seconds=70),
            base_time + timedelta(seconds=80),
        ]

        await executor._monitor_position(
            deal_id="DEAL123",
            epic="TEST",
            direction="BUY",
            entry_price=100,
            current_stop=90,
            atr=5,
            size=1,
        )

    # Verify Force Close
    mock_client.close_open_position.assert_called_once()
    args, _ = mock_client.close_open_position.call_args
    assert args[0] == "DEAL123"
    assert args[1] == "SELL"  # Close BUY with SELL

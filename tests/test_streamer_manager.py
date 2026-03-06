import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from app.streamer.manager import StreamManager, HEALTHY_RUN_THRESHOLD_S


@pytest.mark.asyncio
async def test_process_stream_line_valid_price():
    # Arrange
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock()

    manager = StreamManager(redis_mock)
    manager.candle_builder = MagicMock()
    manager.candle_builder.on_tick = AsyncMock()

    epic = "IX.D.FTSE.DAILY.IP"
    valid_data = {
        "type": "price_update",
        "epic": epic,
        "bid": 8000.5,
        "offer": 8002.5,
        "time": "12:00:00",
    }
    line_str = json.dumps(valid_data)

    # Act
    await manager._process_stream_line(line_str, epic)

    # Assert
    redis_mock.publish.assert_awaited_once_with("market_data", line_str)
    manager.candle_builder.on_tick.assert_awaited_once_with(epic, 8000.5)


@pytest.mark.asyncio
async def test_process_stream_line_negative_price():
    # Arrange
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock()

    manager = StreamManager(redis_mock)
    manager.candle_builder = MagicMock()
    manager.candle_builder.on_tick = AsyncMock()

    epic = "IX.D.FTSE.DAILY.IP"
    invalid_data = {
        "type": "price_update",
        "epic": epic,
        "bid": -100.0,
        "offer": 8002.5,
        "time": "12:00:00",
    }
    line_str = json.dumps(invalid_data)

    # Act
    await manager._process_stream_line(line_str, epic)

    # Assert
    redis_mock.publish.assert_not_awaited()
    manager.candle_builder.on_tick.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_stream_line_zero_price():
    # Arrange
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock()

    manager = StreamManager(redis_mock)
    manager.candle_builder = MagicMock()
    manager.candle_builder.on_tick = AsyncMock()

    epic = "IX.D.FTSE.DAILY.IP"
    invalid_data = {
        "type": "price_update",
        "epic": epic,
        "bid": 0.0,
        "offer": 8002.5,
        "time": "12:00:00",
    }
    line_str = json.dumps(invalid_data)

    # Act
    await manager._process_stream_line(line_str, epic)

    # Assert
    redis_mock.publish.assert_not_awaited()
    manager.candle_builder.on_tick.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_stream_line_insane_price():
    # Arrange
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock()

    manager = StreamManager(redis_mock)
    manager.candle_builder = MagicMock()
    manager.candle_builder.on_tick = AsyncMock()

    epic = "IX.D.FTSE.DAILY.IP"
    invalid_data = {
        "type": "price_update",
        "epic": epic,
        "bid": 2_000_000.0,  # > 1,000,000
        "offer": 2_000_002.0,
        "time": "12:00:00",
    }
    line_str = json.dumps(invalid_data)

    # Act
    await manager._process_stream_line(line_str, epic)

    # Assert
    redis_mock.publish.assert_not_awaited()
    manager.candle_builder.on_tick.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_stream_line_malformed_json():
    # Arrange
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock()

    manager = StreamManager(redis_mock)

    line_str = "NOT_JSON_DATA"
    epic = "IX.D.FTSE.DAILY.IP"

    # Act
    await manager._process_stream_line(line_str, epic)

    # Assert
    redis_mock.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_session_sleeps_on_weekend():
    """When all markets are closed, _run_session should sleep until next open."""
    redis_mock = MagicMock()
    manager = StreamManager(redis_mock)
    manager._notifier = MagicMock()
    manager._notifier.send_notification = AsyncMock()

    wake_time = datetime.now(timezone.utc) + timedelta(hours=10)
    manager._market_status = MagicMock()
    manager._market_status.get_next_streaming_start.return_value = wake_time

    with (
        patch("app.streamer.manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(manager, "_force_reauth", new_callable=AsyncMock, side_effect=Exception("stop")),
    ):
        with pytest.raises(Exception, match="stop"):
            await manager._run_session()

        # Should have slept for approximately 10 hours
        mock_sleep.assert_awaited_once()
        sleep_arg = mock_sleep.call_args[0][0]
        assert sleep_arg > 35000  # ~10 hours in seconds

    manager._notifier.send_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_session_no_sleep_when_open():
    """When a market is open, _run_session should not sleep."""
    redis_mock = MagicMock()
    manager = StreamManager(redis_mock)
    manager._notifier = MagicMock()
    manager._notifier.send_notification = AsyncMock()

    manager._market_status = MagicMock()
    manager._market_status.get_next_streaming_start.return_value = None

    with (
        patch("app.streamer.manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(manager, "_force_reauth", new_callable=AsyncMock, side_effect=Exception("stop")),
    ):
        with pytest.raises(Exception, match="stop"):
            await manager._run_session()

        mock_sleep.assert_not_awaited()

    manager._notifier.send_notification.assert_not_awaited()


def test_backoff_not_reset_at_60s():
    """A process surviving only 60s (JS recovery timeout) should NOT reset backoff."""
    assert 60 <= HEALTHY_RUN_THRESHOLD_S
    assert HEALTHY_RUN_THRESHOLD_S == 90

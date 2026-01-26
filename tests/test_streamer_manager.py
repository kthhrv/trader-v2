import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from app.streamer.manager import StreamManager


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

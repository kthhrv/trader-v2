import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone
from app.services.watcher import PriceSensor


@pytest.mark.asyncio
async def test_price_sensor_window_logic():
    """Test that the sliding window maintains size correctly."""
    sensor = PriceSensor(AsyncMock())
    sensor.window_seconds = 10

    epic = "TEST.EPIC"
    now = datetime.now(timezone.utc)

    # Add old tick
    with patch("app.services.watcher.datetime") as mock_dt:
        mock_dt.now.return_value = now - timedelta(seconds=11)
        await sensor.on_tick({"epic": epic, "bid": 100.0})

    assert len(sensor.windows[epic]) == 1

    # Add new tick
    with patch("app.services.watcher.datetime") as mock_dt:
        mock_dt.now.return_value = now
        await sensor.on_tick({"epic": epic, "bid": 101.0})

    # Old tick should be removed
    assert len(sensor.windows[epic]) == 1
    assert sensor.windows[epic][0][1] == 101.0


@pytest.mark.asyncio
async def test_price_sensor_spike_detection():
    """Test detection of significant price moves."""
    notifier = AsyncMock()
    sensor = PriceSensor(notifier)
    sensor.threshold = 0.005  # 0.5%
    epic = "TEST.EPIC"

    # Base price: 100.0
    await sensor.on_tick({"epic": epic, "bid": 100.0})

    # Small move (0.1%) -> No Alert
    await sensor.on_tick({"epic": epic, "bid": 100.1})
    notifier.send_notification.assert_not_called()

    # Big move (0.6%) -> Alert
    await sensor.on_tick({"epic": epic, "bid": 100.6})
    notifier.send_notification.assert_called_once()
    assert "VOLATILITY ALERT" in notifier.send_notification.call_args[0][0]


@pytest.mark.asyncio
async def test_price_sensor_cooldown():
    """Test that alerts are throttled."""
    notifier = AsyncMock()
    sensor = PriceSensor(notifier)
    sensor.threshold = 0.001
    sensor.cooldown_seconds = 60
    epic = "TEST.EPIC"

    # Trigger 1
    await sensor.on_tick({"epic": epic, "bid": 100.0})
    await sensor.on_tick({"epic": epic, "bid": 102.0})  # Spike

    assert notifier.send_notification.call_count == 1

    # Trigger 2 (Immediate) -> Should be ignored
    await sensor.on_tick({"epic": epic, "bid": 104.0})  # Another Spike
    assert notifier.send_notification.call_count == 1

    # Trigger 3 (After Cooldown) -> Should fire
    with patch("app.services.watcher.datetime") as mock_dt:
        future_now = datetime.now(timezone.utc) + timedelta(seconds=65)
        mock_dt.now.return_value = future_now

        # We need a new "Base" for the comparison because old ticks expired
        # 1. Add Base at T+65
        await sensor.on_tick({"epic": epic, "bid": 100.0})

        # 2. Add Spike at T+65
        await sensor.on_tick({"epic": epic, "bid": 105.0})

    assert notifier.send_notification.call_count == 2

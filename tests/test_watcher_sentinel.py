import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta
import json

from app.services.watcher import MetricSensor
import app.services.watcher as watcher_module


@pytest.fixture
def mock_notifier():
    return AsyncMock()


@pytest.fixture
def sentinel(mock_notifier, monkeypatch):
    # Patch MARKET_CONFIGS in the watcher module
    test_configs = {
        "test_rvol": {"epic": "TEST.RVOL", "name": "Test RVOL"},
        "test_parabolic": {"epic": "TEST.PARABOLIC", "name": "Test Parabolic"},
    }
    monkeypatch.setattr(watcher_module, "MARKET_CONFIGS", test_configs)

    # Patch MarketStatusService to always return open
    monkeypatch.setattr(
        watcher_module.MarketStatusService, "is_market_open", lambda self, epic: True
    )

    s = MetricSensor(mock_notifier)
    s.redis_client = AsyncMock()  # Mock Redis publish
    return s


@pytest.mark.asyncio
async def test_sentinel_buffers_candles(sentinel):
    epic = "TEST.EPIC"

    # Send 5 candles
    for i in range(5):
        data = {
            "epic": epic,
            "timestamp": (
                datetime.now(timezone.utc) + timedelta(minutes=i)
            ).isoformat(),
            "open": 100,
            "high": 105,
            "low": 95,
            "close": 100,
            "volume": 100,
        }
        await sentinel.on_candle(data)

    assert epic in sentinel.history
    assert len(sentinel.history[epic]) == 5


@pytest.mark.asyncio
async def test_sentinel_triggers_rvol(sentinel):
    epic = "TEST.RVOL"

    # Fill history with low volume (Avg = 100)
    for i in range(20):
        data = {
            "epic": epic,
            "timestamp": (
                datetime.now(timezone.utc) + timedelta(minutes=i)
            ).isoformat(),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 100,
        }
        await sentinel.on_candle(data)

    # Send Spike (Vol = 300 -> 3x Avg)
    spike = {
        "epic": epic,
        "timestamp": (datetime.now(timezone.utc) + timedelta(minutes=21)).isoformat(),
        "open": 100,
        "high": 105,
        "low": 95,
        "close": 102,
        "volume": 300,
    }

    # Mock Redis publish to capture output
    sentinel.redis_client.publish = AsyncMock()

    await sentinel.on_candle(spike)

    # Verify Trigger
    sentinel.redis_client.publish.assert_called_once()
    args = sentinel.redis_client.publish.call_args[0]
    assert args[0] == "trade_commands"
    payload = json.loads(args[1])
    assert "RUN_STRATEGY" == payload["command"]
    assert "sentinel_RVOL_SPIKE" in payload["reason"]


@pytest.mark.asyncio
async def test_sentinel_triggers_parabolic(sentinel):
    epic = "TEST.PARABOLIC"

    # Fill history to establish EMA/ATR
    # ATR will be approx 2.0 (High 102, Low 100)
    # EMA will be around 100
    for i in range(25):
        data = {
            "epic": epic,
            "timestamp": (
                datetime.now(timezone.utc) + timedelta(minutes=i)
            ).isoformat(),
            "open": 100,
            "high": 102,
            "low": 100,
            "close": 101,
            "volume": 1000,
        }
        await sentinel.on_candle(data)

    # Send Parabolic Move (Price = 110)
    # EMA ~101. Extension = (110 - 101) / 2 = 4.5x ATR -> Parabolic
    spike = {
        "epic": epic,
        "timestamp": (datetime.now(timezone.utc) + timedelta(minutes=26)).isoformat(),
        "open": 108,
        "high": 110,
        "low": 108,
        "close": 110,
        "volume": 5000,
    }

    sentinel.redis_client.publish = AsyncMock()
    await sentinel.on_candle(spike)

    # Verify Trigger
    sentinel.redis_client.publish.assert_called_once()
    payload = json.loads(sentinel.redis_client.publish.call_args[0][1])
    assert "PARABOLIC_EXT" in payload["reason"]

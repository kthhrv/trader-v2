import pytest
from unittest.mock import AsyncMock, patch
import app.services.watcher as watcher_module
from app.services.watcher import MetricSensor

@pytest.fixture
def mock_notifier():
    return AsyncMock()

@pytest.fixture
def sentinel(mock_notifier, monkeypatch):
    # Patch MARKET_CONFIGS
    test_configs = {
        "test_market": {"epic": "TEST.EPIC", "name": "Test Market"},
    }
    monkeypatch.setattr(watcher_module, "MARKET_CONFIGS", test_configs)
    
    # Patch MarketStatusService
    monkeypatch.setattr(
        watcher_module.MarketStatusService, "is_market_open", lambda self, epic: True
    )
    
    s = MetricSensor(mock_notifier)
    s.redis_client = AsyncMock()
    return s

@pytest.mark.asyncio
async def test_sentinel_respects_monitor_only_mode(sentinel, monkeypatch):
    # Set config to MONITOR_ONLY
    from app.core.config import settings
    monkeypatch.setattr(settings, "SENTINEL_MODE", "MONITOR_ONLY")
    
    # Trigger Logic (Simulate by calling _trigger_bot directly to bypass candle history setup)
    await sentinel._trigger_bot("TEST.EPIC", ["TEST_TRIGGER"], 100.0)
    
    # Verify Notification Sent
    sentinel.notifier.send_notification.assert_called_once()
    
    # Verify Redis NOT called
    sentinel.redis_client.publish.assert_not_called()

@pytest.mark.asyncio
async def test_sentinel_respects_auto_trade_mode(sentinel, monkeypatch):
    # Set config to AUTO_TRADE
    from app.core.config import settings
    monkeypatch.setattr(settings, "SENTINEL_MODE", "AUTO_TRADE")
    
    # Trigger Logic
    await sentinel._trigger_bot("TEST.EPIC", ["TEST_TRIGGER"], 100.0)
    
    # Verify Notification Sent
    sentinel.notifier.send_notification.assert_called_once()
    
    # Verify Redis Called
    sentinel.redis_client.publish.assert_called_once()

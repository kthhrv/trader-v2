import asyncio
import pytest
import socket
from unittest.mock import AsyncMock, MagicMock, patch
import redis.asyncio as redis
from app.services.watcher import WatcherService


@pytest.mark.asyncio
async def test_watcher_reconnects_on_connection_error():
    """
    Verifies that WatcherService retries connection after a Redis ConnectionError.
    """
    notifier_mock = MagicMock()
    watcher = WatcherService(notifier_mock)

    # We want to simulate:
    # 1. First connection attempt succeeds but listen() raises ConnectionError
    # 2. Second connection attempt succeeds and listen() returns a message, then we cancel.

    mock_redis = MagicMock(spec=redis.Redis)
    mock_pubsub = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    mock_redis.close = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()

    # First call to listen() raises error, second returns a generator then ends
    state = {"called": False}

    async def side_effect_listen():
        if state["called"]:
            yield {"type": "message", "data": '{"epic": "TEST", "bid": 100}'}
            # Allow some time then raise CancelledError to stop the loop
            raise asyncio.CancelledError()
        state["called"] = True
        raise redis.ConnectionError("Connection lost")

    mock_pubsub.listen.side_effect = side_effect_listen

    with (
        patch("redis.asyncio.Redis", return_value=mock_redis),
        patch("asyncio.sleep", AsyncMock()) as mock_sleep,
    ):
        await watcher.start()

        # Verify it slept once after the error
        mock_sleep.assert_awaited_once_with(5)
        # Verify it attempted to subscribe twice
        assert mock_pubsub.subscribe.call_count == 2
        # Verify it closed the client on each iteration
        assert mock_redis.close.call_count == 2


@pytest.mark.asyncio
async def test_watcher_reconnects_on_dns_error():
    """
    Verifies that WatcherService retries connection after a DNS failure (socket.gaierror).
    """
    notifier_mock = MagicMock()
    watcher = WatcherService(notifier_mock)

    # Simulate DNS failure on the first redis.Redis() call or subscribe()
    mock_redis = MagicMock(spec=redis.Redis)
    mock_pubsub = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    mock_redis.close = AsyncMock()

    state = {"called": False}

    async def side_effect_subscribe(*args, **kwargs):
        if state["called"]:
            # Stop the loop by cancelling
            raise asyncio.CancelledError()
        state["called"] = True
        raise socket.gaierror(-5, "No address associated with hostname")

    mock_pubsub.subscribe.side_effect = side_effect_subscribe

    with (
        patch("redis.asyncio.Redis", return_value=mock_redis),
        patch("asyncio.sleep", AsyncMock()) as mock_sleep,
    ):
        await watcher.start()

        mock_sleep.assert_awaited_once_with(5)

        assert mock_pubsub.subscribe.call_count == 2

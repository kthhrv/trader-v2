import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import app.adapters.ig_client as igmod
from app.adapters.ig_client import AsyncIGClient, IGAuthenticationError
from app.core.config import settings
from app.streamer.manager import StreamManager


@pytest.fixture(autouse=True)
def _reset_singleton():
    """AsyncIGClient is a process-wide singleton; reset it around each test so a
    shared-session instance never leaks into another test."""
    AsyncIGClient._instance = None
    yield
    AsyncIGClient._instance = None


def test_shared_session_settings_exist():
    # Defaults preserve current behaviour: no shared session.
    assert hasattr(settings, "IG_SHARED_SESSION_URL")
    assert hasattr(settings, "APP_ENV")
    assert settings.IG_SHARED_SESSION_URL == ""


@pytest.mark.asyncio
async def test_url_creates_session_redis(monkeypatch):
    captured = {}

    def fake_from_url(url, decode_responses=False):
        captured["url"] = url
        captured["decode"] = decode_responses
        return AsyncMock()

    monkeypatch.setattr(igmod.settings, "IG_SHARED_SESSION_URL", "redis://192.168.0.191:6387")
    monkeypatch.setattr(igmod.redis, "from_url", fake_from_url)

    client = AsyncIGClient()
    assert client.session_redis is not None
    assert captured["url"] == "redis://192.168.0.191:6387"
    assert captured["decode"] is True


@pytest.mark.asyncio
async def test_flag_off_uses_self_auth(httpx_mock, monkeypatch):
    """Reversibility: empty flag => no shared Redis, legacy POST /session path."""
    monkeypatch.setattr(igmod.settings, "IG_SHARED_SESSION_URL", "")
    httpx_mock.add_response(
        method="POST",
        url="https://api.ig.com/gateway/deal/session",
        status_code=200,
        headers={"CST": "c", "X-SECURITY-TOKEN": "x"},
        json={"currentAccountId": "L12345"},
    )
    client = AsyncIGClient()
    assert client.session_redis is None
    await client.authenticate("LIVE")
    assert client.auth_tokens["LIVE"] == {"CST": "c", "X-SECURITY-TOKEN": "x"}
    await client.close()


@pytest.mark.asyncio
async def test_flag_on_reads_shared_tokens_no_post(httpx_mock, monkeypatch):
    """Flag-on => tokens read from ig_session:live:tokens, headers applied,
    account id from config, and ZERO HTTP requests (no /session POST)."""
    monkeypatch.setattr(igmod.settings, "IG_SHARED_SESSION_URL", "redis://x:6387")
    monkeypatch.setattr(igmod.settings, "APP_ENV", "live")
    monkeypatch.setattr(igmod.redis, "from_url", lambda *a, **k: AsyncMock())

    client = AsyncIGClient()
    client.session_redis.get = AsyncMock(return_value=json.dumps({"cst": "SC", "xst": "SX"}))

    await client.authenticate("LIVE")

    client.session_redis.get.assert_awaited_with("ig_session:live:tokens")
    assert client.auth_tokens["LIVE"] == {"CST": "SC", "X-SECURITY-TOKEN": "SX"}
    assert client.current_account_id == settings.IG_LIVE_ACC_ID
    session = await client._get_session("LIVE")
    assert session.headers["CST"] == "SC"
    assert session.headers["X-SECURITY-TOKEN"] == "SX"
    assert httpx_mock.get_requests() == []  # never POSTed /session
    await client.close()


@pytest.mark.asyncio
async def test_flag_on_missing_tokens_raises(monkeypatch):
    monkeypatch.setattr(igmod.settings, "IG_SHARED_SESSION_URL", "redis://x:6387")
    monkeypatch.setattr(igmod.redis, "from_url", lambda *a, **k: AsyncMock())
    client = AsyncIGClient()
    client.session_redis.get = AsyncMock(return_value=None)
    with pytest.raises(IGAuthenticationError):
        await client.authenticate("LIVE")
    await client.close()


@pytest.mark.asyncio
async def test_streamer_force_reauth_uses_shared_session(httpx_mock, monkeypatch):
    monkeypatch.setattr(igmod.settings, "IG_SHARED_SESSION_URL", "redis://x:6387")
    monkeypatch.setattr(igmod.settings, "APP_ENV", "live")
    monkeypatch.setattr(igmod.redis, "from_url", lambda *a, **k: AsyncMock())

    mgr = StreamManager(MagicMock())  # __init__ builds the shared-session singleton
    mgr.ig_client.session_redis.get = AsyncMock(
        return_value=json.dumps({"cst": "SC", "xst": "SX"})
    )

    tokens = await mgr._force_reauth("LIVE")

    assert tokens == {"CST": "SC", "X-SECURITY-TOKEN": "SX"}
    assert httpx_mock.get_requests() == []  # sidecar feed never POSTed /session
    await mgr.ig_client.close()


@pytest.mark.asyncio
async def test_close_releases_shared_session_redis(monkeypatch):
    monkeypatch.setattr(igmod.settings, "IG_SHARED_SESSION_URL", "redis://x:6387")
    monkeypatch.setattr(igmod.redis, "from_url", lambda *a, **k: AsyncMock())
    client = AsyncIGClient()
    await client.close()
    client.session_redis.aclose.assert_awaited_once()

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

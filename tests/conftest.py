import pytest
import pytest_asyncio
import os
from sqlmodel import SQLModel
from app.database.session import engine as real_engine

# 1. Mock Environment Variables BEFORE importing settings if possible,
# but since app.core.config instantiates 'settings' at module level,
# we must monkeypatch the 'settings' object itself.


@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    """
    Sets dummy environment variables for the entire test session.
    This helps if we re-instantiate Settings or if other libs read os.environ.
    """
    os.environ["IG_DEMO_API_KEY"] = "test_demo_key"
    os.environ["IG_DEMO_USERNAME"] = "test_demo_user"
    os.environ["IG_DEMO_PASSWORD"] = "test_demo_pass"
    os.environ["IG_DEMO_ACC_ID"] = "test_demo_acc"
    os.environ["IG_LIVE_API_KEY"] = "test_live_key"
    os.environ["IG_LIVE_USERNAME"] = "test_live_user"
    os.environ["IG_LIVE_PASSWORD"] = "test_live_pass"
    os.environ["IG_LIVE_ACC_ID"] = "test_live_acc"
    os.environ["GEMINI_API_KEY"] = "test_gemini_key"
    os.environ["TRADING_ACCOUNT_ENV"] = "DEMO"
    os.environ["DATA_ACCOUNT_ENV"] = "DEMO"


@pytest.fixture(autouse=True)
def mock_settings():
    """
    Overrides the global settings object attributes with test values.
    """
    from app.core.config import settings
    from pydantic import SecretStr

    # Store original values to restore after test (optional but good practice)
    # For now, just overwrite for tests

    settings.IG_DEMO_API_KEY = SecretStr("test_demo_key")
    settings.IG_DEMO_USERNAME = "test_demo_user"
    settings.IG_DEMO_PASSWORD = SecretStr("test_demo_pass")
    settings.IG_DEMO_ACC_ID = "test_demo_acc"

    settings.IG_LIVE_API_KEY = SecretStr("test_live_key")
    settings.IG_LIVE_USERNAME = "test_live_user"
    settings.IG_LIVE_PASSWORD = SecretStr("test_live_pass")
    settings.IG_LIVE_ACC_ID = "test_live_acc"

    settings.GEMINI_API_KEY = SecretStr("test_gemini_key")

    settings.TRADING_ACCOUNT_ENV = "DEMO"
    settings.DATA_ACCOUNT_ENV = "LIVE"  # Force LIVE for tests to match mocks

    return settings


@pytest_asyncio.fixture(scope="function", autouse=True)
async def isolate_db():
    # Create tables
    async with real_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    yield

    # Drop tables after test
    async with real_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

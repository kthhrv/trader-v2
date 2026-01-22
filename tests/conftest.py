import pytest
import pytest_asyncio
import os
import tempfile
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel


# 1. Mock Environment Variables
@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
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
    os.environ["DATA_ACCOUNT_ENV"] = "LIVE"
    return


@pytest.fixture(autouse=True)
def mock_settings():
    from app.core.config import settings
    from pydantic import SecretStr

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
    settings.DATA_ACCOUNT_ENV = "LIVE"
    return settings


# 2. Test Database Engine (Temp File)
@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_db(monkeypatch):
    from app.database import session as db_session

    # Create temp file
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        future=True,
    )

    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Create session maker bound to test engine
    test_session_maker = sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )  # type: ignore

    # Monkeypatch the module-level globals in app.database.session
    # All services now import 'app.database.session' module, so patching attributes here propagates.
    monkeypatch.setattr(db_session, "engine", test_engine)
    monkeypatch.setattr(db_session, "async_session_maker", test_session_maker)

    yield

    # Cleanup
    await test_engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)

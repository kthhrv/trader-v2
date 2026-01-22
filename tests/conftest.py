import pytest_asyncio
from sqlmodel import SQLModel
from app.database.session import engine as real_engine


@pytest_asyncio.fixture(scope="function", autouse=True)
async def isolate_db():
    # Create tables
    async with real_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    yield

    # Drop tables after test
    async with real_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

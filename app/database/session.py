from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings

# Create Async Engine
# Note: SQLite requires 3 slashes for relative path, 4 for absolute.
# settings.DB_PATH is absolute, so we use sqlite+aiosqlite:///
DATABASE_URL = f"sqlite+aiosqlite:///{settings.DB_PATH}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL query logging
    future=True,
)

async_session_maker = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)  # type: ignore


async def init_db():
    """
    Initializes the database by creating all tables and enabling WAL mode.
    """
    async with engine.begin() as conn:
        # Enable WAL mode for concurrent access
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        # await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to provide an async database session.
    """
    async with async_session_maker() as session:
        yield session

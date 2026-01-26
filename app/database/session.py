from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings

# Create Async Engine for PostgreSQL
# postgresql+asyncpg://user:password@host:port/dbname
DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:"
    f"{settings.POSTGRES_PASSWORD.get_secret_value()}@"
    f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/"
    f"{settings.POSTGRES_DB}"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL query logging
    future=True,
    pool_size=20,
    max_overflow=10,
)

async_session_maker = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)  # type: ignore


async def init_db():
    """
    Initializes the database by creating tables and setting up TimescaleDB hypertables.
    """
    import app.database.models  # noqa: F401

    async with engine.begin() as conn:
        # 1. Create all tables defined in models.py
        await conn.run_sync(SQLModel.metadata.create_all)

        # 2. Enable TimescaleDB Hypertables for time-series data
        # Note: This is idempotent using 'if_not_exists => TRUE'
        try:
            await conn.execute(
                text(
                    "SELECT create_hypertable('historical_candles', 'timestamp', if_not_exists => TRUE);"
                )
            )
        except Exception as e:
            # If extension is not installed or other PG error, we log but don't crash init
            from app.core.logger import logger

            logger.warning(f"TimescaleDB hypertable setup skipped/failed: {e}")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to provide an async database session.
    """
    async with async_session_maker() as session:
        yield session

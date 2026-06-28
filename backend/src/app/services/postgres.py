"""PostgreSQL client lifecycle helpers."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


def create_postgres_engine(settings: Settings) -> AsyncEngine:
    """Create the process-wide PostgreSQL async engine and pool."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
    )


async def check_postgres(engine: AsyncEngine) -> None:
    """Verify that the pooled Postgres engine can execute a simple query."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_postgres_engine(engine: AsyncEngine) -> None:
    """Release the PostgreSQL engine and its connection pool."""
    await engine.dispose()

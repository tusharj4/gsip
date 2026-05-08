"""pytest fixtures for backend tests — provides a real test PostGIS database session.

Uses pytest-asyncio 0.23 recommended pattern:
- No custom event_loop fixture (deprecated in 0.23)
- Session-scoped engine with module-level schema setup
- Function-scoped session with rollback isolation between tests
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Override DATABASE_URL for tests to use a dedicated test database
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://gsip:gsip_dev@db/gsip_test",
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create the test database engine and run schema setup once per session.

    Uses NullPool so asyncpg does not pool connections across the event loop
    boundaries that pytest-asyncio creates between session and function scopes.
    """
    import app.models  # noqa: F401 — register all ORM models
    from app.database import Base

    eng = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)

    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE EXTENSION IF NOT EXISTS pgrouting;
            EXCEPTION WHEN OTHERS THEN
                RAISE WARNING 'pgRouting not available in test env: %', SQLERRM;
            END $$
        """))
        # Explicitly DROP with CASCADE so PostGIS geometry_columns tracking
        # and FK dependencies are cleaned up before recreating.
        await conn.execute(text("""
            DROP TABLE IF EXISTS
                audit_log, gap_analyses, conflict_reports,
                layer_features, projects, gis_layers, alembic_version
            CASCADE
        """))
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:  # type: ignore[override]
    """Provide a fresh session per test, rolled back after.

    Each test sees a clean slate because the rollback undoes any inserts/
    updates the test performed.  We do NOT use session.begin() as a context
    manager here because the service-layer code (ConflictDetector, GapAnalyser)
    calls flush/execute internally and expects to own its own transaction
    lifecycle within the yielded session.
    """
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

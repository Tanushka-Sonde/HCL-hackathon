"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import Settings
from src.main import create_app


@pytest.fixture(scope="session", autouse=True)
def setup_minio(settings: Settings):
    """Ensure the MinIO bucket exists before tests run."""
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name="us-east-1",
    )

    try:
        s3.head_bucket(Bucket=settings.minio_bucket_name)
    except ClientError:
        s3.create_bucket(Bucket=settings.minio_bucket_name)


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Return a Settings instance with test-safe defaults."""
    return Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
        jwt_secret_key="test-secret-key-not-for-production",
        google_api_key="test-google-key",
        tavily_api_key="test-tavily-key",
        minio_endpoint="http://localhost:9000",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
        app_env="testing",
        log_level="DEBUG",
    )


@pytest_asyncio.fixture(scope="session")
async def engine(settings: Settings) -> AsyncGenerator[AsyncEngine, None]:
    """Create a database engine and run migrations once per session."""
    engine = create_async_engine(settings.database_url, echo=False)

    # Run Alembic migrations synchronously
    def run_migrations(connection, cfg):
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")

    alembic_cfg = Config("alembic.ini")

    async with engine.begin() as conn:
        await conn.run_sync(run_migrations, alembic_cfg)

    yield engine

    async with engine.begin() as conn:
        # We don't drop tables because it's slow, but we could
        pass

    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session and rollback all changes after the test."""
    connection = await engine.connect()
    transaction = await connection.begin()

    session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)

    session = session_factory()
    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest.fixture()
def app(settings: Settings, db_session: AsyncSession) -> FastAPI:
    """Return the FastAPI application instance."""
    app = create_app()
    # Override settings dependency
    from src.auth.dependencies import get_db_session
    from src.core.config import get_settings

    app.dependency_overrides[get_settings] = lambda: settings

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    return app


@pytest_asyncio.fixture()
async def client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Return an async test client."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client

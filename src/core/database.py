"""Async SQLAlchemy engine and session management.

Provides the ``Database`` class which owns the engine and session factory,
and the ``Base`` declarative base for all ORM models.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.core.config import Settings
from src.observability.metrics import db_pool_checkedout, db_pool_size

# Naming conventions for auto-generated constraint names.
# Alembic uses these to produce deterministic, readable migration names.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    """Manages the async SQLAlchemy engine and session factory.

    Usage::

        db = Database(settings)

        async for session in db.session():
            result = await session.execute(...)

    The engine is created lazily on first access.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        """Return the async engine, creating it on first access."""
        if self._engine is None:
            self._engine = create_async_engine(
                self._settings.database_url,
                pool_size=self._settings.database_pool_size,
                max_overflow=self._settings.database_max_overflow,
                pool_timeout=self._settings.database_pool_timeout,
                pool_recycle=self._settings.database_pool_recycle,
                echo=False,
            )
            # Link connection pool metrics to Prometheus gauges
            db_pool_size.set_function(
                lambda: self._engine.sync_engine.pool.size() if self._engine else 0  # type: ignore[attr-defined]
            )
            db_pool_checkedout.set_function(
                lambda: (
                    self._engine.sync_engine.pool.checkedout() if self._engine else 0  # type: ignore[attr-defined]
                )
            )
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the session factory, creating it on first access."""
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        return self._session_factory

    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield an async session with automatic commit/rollback.

        Commits on clean exit, rolls back on any exception.
        """
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        """Dispose the engine and release all pooled connections."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

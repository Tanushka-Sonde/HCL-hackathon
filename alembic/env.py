"""Alembic async migration environment.

Reads the database URL from application settings (not from alembic.ini)
to maintain a single source of truth for configuration.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import all models so they register with Base.metadata.
# These imports are required for autogenerate to detect tables.
from src.auth.models import ApiKey as _ApiKey  # noqa: F401
from src.auth.models import RefreshToken as _RefreshToken  # noqa: F401
from src.auth.models import User as _User  # noqa: F401
from src.core.config import get_settings
from src.core.database import Base
from src.documents.models import Document as _Document  # noqa: F401
from src.ingestion.models import Chunk as _Chunk  # noqa: F401
from src.ingestion.models import IngestionJob as _IngestionJob  # noqa: F401
from src.tenants.models import Organization as _Organization  # noqa: F401
from src.tenants.models import OrgMembership as _OrgMembership  # noqa: F401

config = context.config
target_metadata = Base.metadata

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from application settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    """Configure context and run migrations within a connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live database)."""
    connectable = config.attributes.get("connection", None)

    if connectable is not None:
        do_run_migrations(connectable)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Tenant context helpers.

FastAPI resolves the current tenant through dependencies, then sets the
PostgreSQL session variable used by Row-Level Security policies.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Set the request-local tenant variable consumed by RLS policies."""
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def set_worker_context(db: AsyncSession) -> None:
    """Allow ingestion workers to process queue rows across tenants."""
    await db.execute(text("SELECT set_config('app.worker_mode', 'on', true)"))

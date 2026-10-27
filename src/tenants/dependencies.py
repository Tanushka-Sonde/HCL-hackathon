"""FastAPI dependencies for resolving the current tenant."""

from __future__ import annotations

import uuid

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user, get_db_session
from src.auth.models import User
from src.core.config import get_settings
from src.core.exceptions import RateLimitError, ValidationError
from src.core.rate_limit import RateLimiter, get_rate_limiter
from src.tenants import service as tenant_service
from src.tenants.middleware import set_tenant_context
from src.tenants.schemas import TenantContext


async def get_current_tenant(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> TenantContext:
    """Resolve and activate the tenant for a request."""
    try:
        requested_org_id = uuid.UUID(x_tenant_id) if x_tenant_id else None
    except ValueError as exc:
        raise ValidationError("X-Tenant-ID must be a valid UUID.") from exc

    membership = await tenant_service.resolve_membership(
        user_id=user.id,
        org_id=requested_org_id,
        db=db,
    )

    settings = get_settings()
    key = f"ratelimit:tenant:{membership.org_id}"
    allowed = await limiter.is_allowed(
        key=key,
        max_requests=settings.rate_limit_requests,
        window=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise RateLimitError()

    await set_tenant_context(db, membership.org_id)
    return TenantContext(org_id=membership.org_id, role=membership.role)

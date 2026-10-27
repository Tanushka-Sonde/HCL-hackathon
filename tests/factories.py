"""Test factories for generating test data."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.auth.service import register_user
from src.tenants.models import Organization


async def create_test_user(
    db: AsyncSession,
    email: str = "test@example.com",
    password: str = "password123",
    full_name: str = "Test User",
) -> User:
    """Create a user and their personal workspace."""
    # register_user automatically creates the personal workspace organization
    user = await register_user(
        email=email,
        password=password,
        db=db,
    )
    return user


async def get_user_workspace(user: User, db: AsyncSession) -> Organization:
    """Get the auto-generated personal workspace for a user."""
    from sqlalchemy import select

    from src.tenants.models import OrgMembership

    result = await db.execute(
        select(Organization).join(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    return result.scalars().first()

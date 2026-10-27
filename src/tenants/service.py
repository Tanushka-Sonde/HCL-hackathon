"""Tenant and organization business logic."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from src.tenants.models import Organization, OrgMembership, OrganizationInvite

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Convert an organization name into a stable URL-safe slug."""
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "organization"


async def create_organization(
    *,
    name: str,
    owner_id: uuid.UUID,
    db: AsyncSession,
    slug: str | None = None,
) -> Organization:
    """Create an organization and make the creator an admin."""
    organization = Organization(name=name, slug=slug or slugify(name))
    try:
        db.add(organization)
        await db.flush()

        db.add(
            OrgMembership(
                org_id=organization.id,
                user_id=owner_id,
                role="admin",
            )
        )
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("Organization slug already exists.") from exc

    return organization


async def create_personal_organization(
    *,
    user_id: uuid.UUID,
    email: str,
    db: AsyncSession,
) -> Organization:
    """Create the default personal tenant for a newly registered user."""
    base = email.split("@", 1)[0]
    return await create_organization(
        name=f"{base}'s Workspace",
        slug=f"user-{user_id}",
        owner_id=user_id,
        db=db,
    )


async def list_memberships(
    *,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[OrgMembership]:
    """List organizations a user belongs to."""
    result = await db.execute(
        select(OrgMembership)
        .where(OrgMembership.user_id == user_id)
        .options(selectinload(OrgMembership.organization))
        .order_by(OrgMembership.created_at.asc())
    )
    return list(result.scalars().all())


async def resolve_membership(
    *,
    user_id: uuid.UUID,
    db: AsyncSession,
    org_id: uuid.UUID | None = None,
) -> OrgMembership:
    """Resolve requested tenant or the user's default tenant."""
    query = (
        select(OrgMembership)
        .where(OrgMembership.user_id == user_id)
        .options(selectinload(OrgMembership.organization))
        .order_by(OrgMembership.created_at.asc())
    )
    if org_id is not None:
        query = query.where(OrgMembership.org_id == org_id)

    result = await db.execute(query)
    membership = result.scalars().first()

    if membership is None and org_id is not None:
        raise AuthorizationError("You are not a member of this organization.")
    if membership is None:
        raise NotFoundError("Organization membership", str(user_id))

    return membership


def require_role(role: str, allowed: set[str]) -> None:
    """Raise unless ``role`` is included in ``allowed``."""
    if role not in allowed:
        raise AuthorizationError("Insufficient organization role.")


async def list_org_members(
    *,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict]:
    """List all members of an organization with their email addresses."""
    from src.auth.models import User

    result = await db.execute(
        select(OrgMembership)
        .where(OrgMembership.org_id == org_id)
        .options(selectinload(OrgMembership.user))
        .order_by(OrgMembership.created_at.asc())
    )
    memberships = result.scalars().all()
    return [
        {
            "id": m.id,
            "user_id": m.user_id,
            "role": m.role,
            "email": m.user.email,
            "created_at": m.created_at,
        }
        for m in memberships
    ]


async def remove_member(
    *,
    org_id: uuid.UUID,
    user_id_to_remove: uuid.UUID,
    current_user_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Remove a member from an organization."""
    if user_id_to_remove == current_user_id:
        raise ConflictError("You cannot remove yourself from the organization.")

    result = await db.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id_to_remove,
        )
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise NotFoundError("Organization membership", str(user_id_to_remove))

    await db.delete(membership)
    await db.flush()


async def create_invite(
    *,
    org_id: uuid.UUID,
    email: str,
    role: str,
    inviter_id: uuid.UUID,
    db: AsyncSession,
) -> OrganizationInvite:
    """Create a new invitation to join an organization."""
    # Check if user is already a member
    from src.auth.models import User
    existing_user = await db.execute(select(User).where(User.email == email))
    user = existing_user.scalar_one_or_none()
    
    if user:
        existing_membership = await db.execute(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == user.id
            )
        )
        if existing_membership.scalar_one_or_none():
            raise ConflictError("User is already a member of this organization.")

    # Check for existing pending invite
    existing_invite = await db.execute(
        select(OrganizationInvite).where(
            OrganizationInvite.org_id == org_id,
            OrganizationInvite.email == email,
            OrganizationInvite.status == "pending"
        )
    )
    if existing_invite.scalar_one_or_none():
        raise ConflictError("A pending invitation already exists for this email.")

    import secrets
    import hashlib
    from datetime import datetime, UTC, timedelta

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(days=7)

    invite = OrganizationInvite(
        org_id=org_id,
        email=email,
        role=role,
        token_hash=token_hash,
        expires_at=expires_at,
        created_by=inviter_id,
    )
    db.add(invite)
    await db.flush()

    # Re-query with eagerly loaded organization for the response serializer
    result = await db.execute(
        select(OrganizationInvite)
        .where(OrganizationInvite.id == invite.id)
        .options(selectinload(OrganizationInvite.organization))
    )
    invite = result.scalar_one()

    # In a real system, you would email `raw_token` to the user here.
    return invite


async def list_pending_invites(
    *,
    email: str,
    db: AsyncSession,
) -> list[OrganizationInvite]:
    """List all pending invites for a specific email."""
    result = await db.execute(
        select(OrganizationInvite)
        .where(
            OrganizationInvite.email == email,
            OrganizationInvite.status == "pending"
        )
        .options(selectinload(OrganizationInvite.organization))
        .order_by(OrganizationInvite.created_at.desc())
    )
    return list(result.scalars().all())


async def accept_invite(
    *,
    invite_id: uuid.UUID,
    user_id: uuid.UUID,
    email: str,
    db: AsyncSession,
) -> OrgMembership:
    """Accept an invitation and join the organization."""
    from datetime import datetime, UTC

    result = await db.execute(
        select(OrganizationInvite)
        .where(
            OrganizationInvite.id == invite_id,
            OrganizationInvite.email == email,
        )
        # Lock for update to prevent concurrent double-accept
        .with_for_update()
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise NotFoundError("Invitation", str(invite_id))
    
    if invite.status != "pending":
        raise ConflictError(f"Invitation is already {invite.status}.")
    
    if invite.expires_at < datetime.now(UTC):
        invite.status = "expired"
        await db.flush()
        raise ConflictError("Invitation has expired.")

    # Create membership
    membership = OrgMembership(
        org_id=invite.org_id,
        user_id=user_id,
        role=invite.role,
    )
    db.add(membership)

    # Mark invite as accepted
    invite.status = "accepted"
    invite.accepted_at = datetime.now(UTC)
    
    await db.flush()

    # Re-query with eagerly loaded organization for the response serializer
    result = await db.execute(
        select(OrgMembership)
        .where(OrgMembership.id == membership.id)
        .options(selectinload(OrgMembership.organization))
    )
    membership = result.scalar_one()

    return membership


"""Organization and tenant API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user, get_db_session
from src.auth.models import User
from src.tenants import service as tenant_service
from src.tenants.schemas import (
    MembershipResponse,
    OrgMemberResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationInviteCreateRequest,
    OrganizationInviteResponse,
)
from src.tenants.dependencies import get_current_tenant
from src.tenants.schemas import TenantContext

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    body: OrganizationCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OrganizationResponse:
    """Create a new organization owned by the current user."""
    organization = await tenant_service.create_organization(
        name=body.name,
        slug=body.slug,
        owner_id=user.id,
        db=db,
    )
    return OrganizationResponse.model_validate(organization)


@router.get("", response_model=list[MembershipResponse])
async def list_organizations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[MembershipResponse]:
    """List organizations available to the current user."""
    memberships = await tenant_service.list_memberships(user_id=user.id, db=db)
    return [MembershipResponse.model_validate(item) for item in memberships]


@router.get("/members", response_model=list[OrgMemberResponse])
async def list_members(
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> list[OrgMemberResponse]:
    """List all members of the current organization."""
    members = await tenant_service.list_org_members(org_id=tenant.org_id, db=db)
    return [OrgMemberResponse.model_validate(m) for m in members]

@router.delete("/members/{user_id_to_remove}", status_code=204)
async def remove_member(
    user_id_to_remove: uuid.UUID,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Remove a member from the current organization."""
    tenant_service.require_role(tenant.role, {"admin"})
    await tenant_service.remove_member(
        org_id=tenant.org_id,
        user_id_to_remove=user_id_to_remove,
        current_user_id=user.id,
        db=db,
    )


@router.post("/invites", response_model=OrganizationInviteResponse, status_code=201)
async def create_invite(
    body: OrganizationInviteCreateRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> OrganizationInviteResponse:
    """Create a new invitation for a user to join the current organization."""
    tenant_service.require_role(tenant.role, {"admin"})
    invite = await tenant_service.create_invite(
        org_id=tenant.org_id,
        email=body.email,
        role=body.role,
        inviter_id=user.id,
        db=db,
    )
    return OrganizationInviteResponse.model_validate(invite)


@router.get("/invites/pending", response_model=list[OrganizationInviteResponse])
async def list_pending_invites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[OrganizationInviteResponse]:
    """List pending organization invites for the authenticated user's email."""
    invites = await tenant_service.list_pending_invites(email=user.email, db=db)
    return [OrganizationInviteResponse.model_validate(i) for i in invites]


@router.post("/invites/{invite_id}/accept", response_model=MembershipResponse)
async def accept_invite(
    invite_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MembershipResponse:
    """Accept an invitation to join an organization."""
    membership = await tenant_service.accept_invite(
        invite_id=invite_id,
        user_id=user.id,
        email=user.email,
        db=db,
    )
    return MembershipResponse.model_validate(membership)

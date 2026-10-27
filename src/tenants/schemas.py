"""Pydantic schemas for organization and membership endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrganizationCreateRequest(BaseModel):
    """Request body for creating an organization."""

    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=3, max_length=100)


class OrganizationResponse(BaseModel):
    """Public organization representation."""

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MembershipResponse(BaseModel):
    """Organization membership returned to clients."""

    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    organization: OrganizationResponse

    model_config = {"from_attributes": True}


class OrgMemberResponse(BaseModel):
    """A member of an organization, including their email."""

    id: uuid.UUID
    user_id: uuid.UUID
    role: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantContext(BaseModel):
    """Resolved tenant for the current request."""

    org_id: uuid.UUID
    role: str


class OrganizationInviteCreateRequest(BaseModel):
    """Request body for inviting a user."""

    email: str = Field(pattern=r"^[^@]+@[^@]+\.[^@]+$")
    role: str = Field(default="viewer", pattern="^(admin|editor|viewer)$")


class OrganizationInviteResponse(BaseModel):
    """Public representation of an organization invite."""

    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime
    organization: OrganizationResponse

    model_config = {"from_attributes": True}

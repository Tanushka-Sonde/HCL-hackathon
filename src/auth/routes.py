"""Authentication API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import service as auth_service
from src.auth.dependencies import get_current_user, get_db_session
from src.auth.models import User
from src.auth.schemas import (
    AccessTokenResponse,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    GoogleLoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from src.core.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google-login", response_model=TokenResponse)
async def google_login(
    body: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Authenticate and receive access + refresh tokens using a Google id_token."""
    access_token, refresh_token = await auth_service.google_login(
        body.credential, db, settings
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AccessTokenResponse:
    """Exchange a refresh token for new access + refresh tokens.

    The old refresh token is invalidated (one-time use).
    """
    access_token, new_refresh = await auth_service.refresh_access_token(
        body.refresh_token, db, settings
    )
    return AccessTokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the currently authenticated user."""
    return UserResponse.model_validate(user)


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ApiKeyCreatedResponse:
    """Create a new API key. The full key is shown only once."""
    full_key, api_key = await auth_service.create_user_api_key(user.id, body.name, db)
    return ApiKeyCreatedResponse(
        key=full_key,
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.key_prefix,
        created_at=api_key.created_at,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ApiKeyResponse]:
    """List all API keys for the current user."""
    keys = await auth_service.list_user_api_keys(user.id, db)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Revoke an API key. Cannot be undone."""
    await auth_service.revoke_user_api_key(user.id, key_id, db)

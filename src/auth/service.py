"""Authentication business logic.

All database queries and mutations live here. Route handlers delegate
to these functions and never execute queries directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.models import ApiKey, RefreshToken, User
from src.core.config import Settings
from src.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
)
from src.core.logging import get_logger
from src.core.security import (
    create_access_token,
    generate_api_key,
    generate_refresh_token,
    hash_refresh_token,
)

logger = get_logger(__name__)


from google.oauth2 import id_token
from google.auth.transport import requests

# ── Google Login ─────────────────────────────────────────────

async def google_login(
    credential: str,
    db: AsyncSession,
    settings: Settings,
) -> tuple[str, str]:
    """Authenticate a user via Google OAuth id_token.
    
    If the user doesn't exist, create them. Returns access + refresh tokens.
    """
    try:
        # We need a google-auth Request object. It does blocking I/O for certs,
        # but the cache usually prevents actual network calls after the first time.
        request = requests.Request()
        id_info = id_token.verify_oauth2_token(credential, request)
        email = id_info.get("email")
        if not email:
            raise AuthenticationError("Google token missing email.")
    except ValueError as exc:
        logger.warning("google_token_verification_failed", error=str(exc))
        raise AuthenticationError("Invalid Google token.") from exc

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=email)
        db.add(user)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise ConflictError(f"User with email '{email}' already exists.") from exc

        from src.tenants.service import create_personal_organization
        await create_personal_organization(user_id=user.id, email=user.email, db=db)
        logger.info("user_registered_via_google", user_id=str(user.id), email=email)

    if not user.is_active:
        raise AuthenticationError("Account is deactivated.")

    access_token = create_access_token(str(user.id), user.email, settings)
    raw_refresh, refresh_hash, expires_at = generate_refresh_token(settings)

    refresh = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=expires_at,
    )
    db.add(refresh)
    await db.flush()

    logger.info("user_logged_in_via_google", user_id=str(user.id))
    return access_token, raw_refresh


# ── Token Refresh ────────────────────────────────────────────


async def refresh_access_token(
    raw_token: str,
    db: AsyncSession,
    settings: Settings,
) -> tuple[str, str]:
    """Rotate a refresh token and issue a new access token.

    The old refresh token is deleted (one-time use).
    A new refresh token is created and returned.

    Returns:
        Tuple of (access_token, new_raw_refresh_token).

    Raises:
        AuthenticationError: If the refresh token is invalid, expired,
            or the user is deactivated.
    """
    token_hash = hash_refresh_token(raw_token)

    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .options(selectinload(RefreshToken.user))
    )
    stored = result.scalar_one_or_none()

    if stored is None:
        raise AuthenticationError("Invalid refresh token.")

    if stored.expires_at < datetime.now(UTC):
        # Clean up expired token
        await db.delete(stored)
        await db.flush()
        raise AuthenticationError("Refresh token has expired.")

    if not stored.user.is_active:
        raise AuthenticationError("Account is deactivated.")

    # Delete old token (rotation — prevents replay)
    await db.delete(stored)

    # Issue new tokens
    access_token = create_access_token(str(stored.user.id), stored.user.email, settings)
    new_raw, new_hash, new_expires = generate_refresh_token(settings)

    new_refresh = RefreshToken(
        user_id=stored.user.id,
        token_hash=new_hash,
        expires_at=new_expires,
    )
    db.add(new_refresh)
    await db.flush()

    logger.info("token_refreshed", user_id=str(stored.user.id))
    return access_token, new_raw


# ── API Keys ─────────────────────────────────────────────────


async def create_user_api_key(
    user_id: uuid.UUID,
    name: str,
    db: AsyncSession,
) -> tuple[str, ApiKey]:
    """Generate a new API key for the user.

    Returns:
        Tuple of (full_key, ApiKey model). The full key is shown to the
        user exactly once and is never stored in plaintext.
    """
    full_key, prefix, key_hash = generate_api_key()

    api_key = ApiKey(
        user_id=user_id,
        key_prefix=prefix,
        key_hash=key_hash,
        name=name,
    )
    db.add(api_key)
    await db.flush()

    logger.info(
        "api_key_created",
        user_id=str(user_id),
        key_prefix=prefix,
        name=name,
    )
    return full_key, api_key


async def list_user_api_keys(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[ApiKey]:
    """List all API keys for a user (active and revoked)."""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_user_api_key(
    user_id: uuid.UUID,
    key_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Revoke an API key.

    Raises:
        NotFoundError: If the key does not exist or belongs to a
            different user.
    """
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == user_id,
        )
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise NotFoundError("API key", str(key_id))

    api_key.is_active = False
    await db.flush()

    logger.info(
        "api_key_revoked",
        user_id=str(user_id),
        key_id=str(key_id),
    )

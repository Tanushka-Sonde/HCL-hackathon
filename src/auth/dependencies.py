"""FastAPI dependencies for database sessions and authentication."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.models import ApiKey, User
from src.core.config import Settings, get_settings
from src.core.database import Database
from src.core.exceptions import AuthenticationError
from src.core.security import (
    API_KEY_PREFIX,
    decode_access_token,
    verify_api_key,
)

# Optional bearer scheme — does not return 401 automatically so we
# can provide our own error messages.
_bearer_scheme = HTTPBearer(auto_error=False)


# ── Database Session ─────────────────────────────────────────


async def get_db_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async session.

    Commits on clean exit, rolls back on any exception.
    Session is closed automatically by the context manager.
    """
    db: Database = request.app.state.db
    async with db.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Authentication ───────────────────────────────────────────


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    """Extract and validate the current user from the Authorization header.

    Supports two authentication methods:
    - JWT access token: ``Authorization: Bearer <jwt>``
    - API key: ``Authorization: Bearer sk-<key>``

    The prefix ``sk-`` distinguishes API keys from JWT tokens.

    Raises:
        AuthenticationError: If credentials are missing, invalid, or the
            user is deactivated.
    """
    if credentials is None:
        raise AuthenticationError("Missing authorization header.")

    token = credentials.credentials

    if token.startswith(API_KEY_PREFIX):
        return await _authenticate_api_key(token, db)
    return await _authenticate_jwt(token, db, settings)


# ── Internal Helpers ─────────────────────────────────────────


async def _authenticate_jwt(
    token: str,
    db: AsyncSession,
    settings: Settings,
) -> User:
    """Validate a JWT access token and return the associated user."""
    payload = decode_access_token(token, settings)

    result = await db.execute(select(User).where(User.id == uuid.UUID(payload.user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise AuthenticationError("User not found.")
    if not user.is_active:
        raise AuthenticationError("Account is deactivated.")

    return user


async def _authenticate_api_key(
    raw_key: str,
    db: AsyncSession,
) -> User:
    """Validate an API key and return the associated user.

    Lookup strategy: find active keys by prefix (partial index),
    then bcrypt-verify the full key. This avoids loading all keys.
    """
    prefix = raw_key[:12]

    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.key_prefix == prefix, ApiKey.is_active.is_(True))
        .options(selectinload(ApiKey.user))
    )
    candidates = result.scalars().all()

    for key in candidates:
        if verify_api_key(raw_key, key.key_hash):
            if not key.user.is_active:
                raise AuthenticationError("Account is deactivated.")
            # Update last-used timestamp
            key.last_used_at = datetime.now(UTC)
            return key.user

    raise AuthenticationError("Invalid API key.")

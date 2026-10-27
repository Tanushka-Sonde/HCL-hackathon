"""Authentication utilities: JWT tokens, password hashing, API key management.

All cryptographic operations use established libraries (bcrypt, PyJWT).
No custom crypto.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from src.core.config import Settings
from src.core.exceptions import AuthenticationError

# ── Constants ────────────────────────────────────────────────

BCRYPT_ROUNDS: int = 12
API_KEY_PREFIX: str = "sk-"
API_KEY_BYTE_LENGTH: int = 32


# ── Data Structures ──────────────────────────────────────────


class TokenPayload:
    """Decoded JWT access token payload."""

    __slots__ = ("email", "exp", "user_id")

    def __init__(self, user_id: str, email: str, exp: float) -> None:
        self.user_id = user_id
        self.email = email
        self.exp = exp


# ── Password Hashing ────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt with 12 rounds."""
    hashed = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    )
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Returns False (never raises) for invalid inputs.
    """
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            hashed.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


# ── JWT Access Tokens ────────────────────────────────────────


def create_access_token(
    user_id: str,
    email: str,
    settings: Settings,
) -> str:
    """Create a signed JWT access token.

    Token contains: sub (user_id), email, exp, iat, type.
    """
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "iat": now,
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str, settings: Settings) -> TokenPayload:
    """Decode and validate a JWT access token.

    Raises:
        AuthenticationError: If the token is invalid, expired, or has
            wrong type.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Access token has expired.")
    except jwt.InvalidTokenError:
        raise AuthenticationError("Invalid access token.")

    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type.")

    user_id = payload.get("sub")
    email = payload.get("email")
    exp = payload.get("exp")

    if not user_id or not email or exp is None:
        raise AuthenticationError("Malformed token payload.")

    return TokenPayload(user_id=user_id, email=email, exp=float(exp))


# ── Refresh Tokens ───────────────────────────────────────────


def generate_refresh_token(
    settings: Settings,
) -> tuple[str, str, datetime]:
    """Generate an opaque refresh token.

    Returns:
        Tuple of (raw_token, sha256_hash, expiry_datetime).
        Send raw_token to client. Store sha256_hash in database.
    """
    raw_token = secrets.token_urlsafe(API_KEY_BYTE_LENGTH)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    return raw_token, token_hash, expires_at


def hash_refresh_token(raw_token: str) -> str:
    """Hash a raw refresh token for database lookup."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# ── API Keys ─────────────────────────────────────────────────


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        Tuple of (full_key, prefix_for_display, bcrypt_hash).
        Show full_key to user exactly once. Store prefix + hash in DB.
    """
    random_part = secrets.token_urlsafe(API_KEY_BYTE_LENGTH)
    full_key = f"{API_KEY_PREFIX}{random_part}"
    prefix = full_key[:12]
    key_hash = bcrypt.hashpw(
        full_key.encode("utf-8"),
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    )
    return full_key, prefix, key_hash.decode("utf-8")


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Verify an API key against its stored bcrypt hash.

    Returns False (never raises) for invalid inputs.
    """
    try:
        return bcrypt.checkpw(
            raw_key.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False

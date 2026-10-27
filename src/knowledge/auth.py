"""Username/password authentication and roles for demo mode.

Two roles: ``admin`` (knowledge base, observability, users) and ``user``
(the assistant only). Passwords are bcrypt-hashed and tokens are signed JWTs
from ``src.core.security``. The token only identifies the user; the role is
read from the database on every request, so deactivating a user or changing
their role takes effect immediately. All checks run server-side.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from src.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ValidationError,
)
from src.core.logging import get_logger
from src.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

if TYPE_CHECKING:
    from src.core.config import Settings
    from src.knowledge.store import KnowledgeStore

logger = get_logger(__name__)

Role = Literal["admin", "user"]
PLACEHOLDER_SECRET = "change-me-to-a-random-256-bit-hex-string"

# Accounts created by scripts/seed_demo.py (synthetic demo data only).
DEMO_USERS: list[tuple[str, str, Role]] = [
    ("admin", "admin123", "admin"),
    ("alice", "user123", "user"),
    ("bob", "user123", "user"),
]

# Identity used for evaluation runs, which are started by an admin.
SYSTEM_EVAL_USER = {"id": "system-eval", "username": "eval-runner", "role": "admin"}

# A dummy hash so unknown usernames take as long to reject as wrong passwords.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class CurrentUser:
    id: str
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "username": self.username, "role": self.role}


class AuthService:
    """Login, token checks and user management over the knowledge store."""

    def __init__(self, store: KnowledgeStore, settings: Settings) -> None:
        self.store = store
        secret = settings.jwt_secret_key
        if not secret or secret == PLACEHOLDER_SECRET:
            # Never sign tokens with a publicly known value. A per-process
            # secret is safe but logs everyone out on restart.
            secret = secrets.token_hex(32)
            logger.warning(
                "kis_jwt_secret_not_set",
                hint="set JWT_SECRET_KEY in .env so logins survive restarts",
            )
        self._token_settings = settings.model_copy(
            update={
                "jwt_secret_key": secret,
                "jwt_access_token_expire_minutes": settings.kis_token_expire_minutes,
            }
        )

    # ── Users ────────────────────────────────────────────────

    def create_user(self, username: str, password: str, role: Role) -> dict:
        username = username.strip().lower()
        if not username.replace("_", "").replace(".", "").isalnum():
            raise ValidationError(
                "Username may contain only letters, digits, '.' and '_'."
            )
        if len(password) < 6:
            raise ValidationError("Password must be at least 6 characters.")
        if role not in ("admin", "user"):
            raise ValidationError("Role must be 'admin' or 'user'.")
        if self.store.get_user_credentials(username):
            raise ConflictError(f"User '{username}' already exists.")
        user_id = str(uuid.uuid4())
        self.store.create_user(
            {
                "id": user_id,
                "username": username,
                "password_hash": hash_password(password),
                "role": role,
                "is_active": 1,
                "created_at": _now(),
            }
        )
        return self.store.get_user(user_id) or {}

    def ensure_demo_users(self) -> list[str]:
        """Create the demo accounts that do not exist yet; return their names."""
        created = []
        for username, password, role in DEMO_USERS:
            if not self.store.get_user_credentials(username):
                self.create_user(username, password, role)
                created.append(username)
        return created

    # ── Login and tokens ─────────────────────────────────────

    def login(self, username: str, password: str, ip: str | None) -> dict:
        username = username.strip().lower()
        creds = self.store.get_user_credentials(username)
        ok = verify_password(password, creds["password_hash"] if creds else _DUMMY_HASH)
        if not (creds and ok and creds["is_active"]):
            self.store.record_auth_event(
                "login_failed",
                False,
                _now(),
                username=username,
                user_id=creds["id"] if creds else None,
                ip=ip,
            )
            # Same message for every failure: do not reveal which part was wrong.
            raise AuthenticationError("Invalid username or password.")
        self.store.record_auth_event(
            "login", True, _now(), username=username, user_id=creds["id"], ip=ip
        )
        token = create_access_token(creds["id"], username, self._token_settings)
        return {
            "access_token": token,
            "token_type": "bearer",
            "username": username,
            "role": creds["role"],
            "expires_in_minutes": self._token_settings.jwt_access_token_expire_minutes,
        }

    def authenticate(self, authorization: str | None) -> CurrentUser:
        """Resolve a ``Bearer`` header to an active user, or raise 401."""
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthenticationError("Sign in to continue.")
        payload = decode_access_token(authorization[7:].strip(), self._token_settings)
        user = self.store.get_user(payload.user_id)
        if user is None or not user["is_active"]:
            raise AuthenticationError("This account is not active.")
        return CurrentUser(user["id"], user["username"], user["role"])

    def require_admin(self, user: CurrentUser, path: str, ip: str | None) -> None:
        if user.is_admin:
            return
        self.store.record_auth_event(
            "forbidden",
            False,
            _now(),
            username=user.username,
            user_id=user.id,
            ip=ip,
            detail=path,
        )
        raise AuthorizationError("This action requires an administrator.")

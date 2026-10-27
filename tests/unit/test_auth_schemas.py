"""Unit tests for auth schemas (validation logic, no DB required)."""

from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from src.auth.schemas import (
    CreateApiKeyRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)


class TestRegisterRequest:
    def test_valid_registration(self) -> None:
        req = RegisterRequest(email="user@example.com", password="securepass123")
        assert req.email == "user@example.com"

    def test_email_normalized_to_lowercase(self) -> None:
        req = RegisterRequest(email="User@Example.COM", password="securepass123")
        assert req.email == "user@example.com"

    def test_invalid_email_rejected(self) -> None:
        with pytest.raises(ValidationError, match="email"):
            RegisterRequest(email="not-an-email", password="securepass123")

    def test_email_without_domain_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RegisterRequest(email="user@", password="securepass123")

    def test_short_password_rejected(self) -> None:
        with pytest.raises(ValidationError, match="String should have at least 8"):
            RegisterRequest(email="user@example.com", password="short")

    def test_long_password_rejected(self) -> None:
        with pytest.raises(ValidationError, match="String should have at most 128"):
            RegisterRequest(email="user@example.com", password="x" * 129)

    def test_empty_email_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RegisterRequest(email="", password="securepass123")


class TestLoginRequest:
    def test_valid_login(self) -> None:
        req = LoginRequest(email="User@Example.com", password="anypass")
        assert req.email == "user@example.com"

    def test_any_password_length_accepted(self) -> None:
        """Login does not enforce password rules — that's registration's job."""
        req = LoginRequest(email="user@example.com", password="x")
        assert req.password == "x"


class TestCreateApiKeyRequest:
    def test_valid_name(self) -> None:
        req = CreateApiKeyRequest(name="my-key")
        assert req.name == "my-key"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least 1"):
            CreateApiKeyRequest(name="")

    def test_long_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at most 100"):
            CreateApiKeyRequest(name="x" * 101)


class TestTokenResponse:
    def test_defaults(self) -> None:
        resp = TokenResponse(
            access_token="access",
            refresh_token="refresh",
        )
        assert resp.token_type == "bearer"


class TestUserResponse:
    def test_from_attributes(self) -> None:
        """Verify model_config allows ORM model conversion."""
        import uuid
        from datetime import datetime

        # Simulate an ORM object with attributes
        class FakeUser:
            id = uuid.uuid4()
            email = "test@example.com"
            is_active = True
            created_at = datetime.now(UTC)

        resp = UserResponse.model_validate(FakeUser())
        assert resp.email == "test@example.com"
        assert resp.is_active is True

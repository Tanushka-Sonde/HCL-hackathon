"""Unit tests for src.core.security."""

from __future__ import annotations

import time
from datetime import UTC

import pytest

from src.core.config import Settings
from src.core.exceptions import AuthenticationError
from src.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_api_key,
    verify_password,
)

# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture()
def auth_settings() -> Settings:
    return Settings(
        jwt_secret_key="test-secret-256-bit-hex",
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=15,
        jwt_refresh_token_expire_days=7,
        app_env="testing",
    )


# ── Password Hashing ────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_and_verify_correct_password(self) -> None:
        password = "S3cur3P@ssw0rd!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_wrong_password(self) -> None:
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_not_plaintext(self) -> None:
        password = "my-secret"
        hashed = hash_password(password)
        assert hashed != password
        assert hashed.startswith("$2")  # bcrypt marker

    def test_different_hashes_for_same_password(self) -> None:
        password = "same-password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2  # Different salts

    def test_verify_with_invalid_hash_returns_false(self) -> None:
        assert verify_password("password", "not-a-valid-hash") is False

    def test_verify_with_empty_password(self) -> None:
        hashed = hash_password("real-password")
        assert verify_password("", hashed) is False


# ── JWT Access Tokens ────────────────────────────────────────


class TestJWT:
    def test_create_and_decode_token(self, auth_settings: Settings) -> None:
        token = create_access_token(
            user_id="user-123",
            email="test@example.com",
            settings=auth_settings,
        )
        payload = decode_access_token(token, auth_settings)
        assert payload.user_id == "user-123"
        assert payload.email == "test@example.com"

    def test_expired_token_raises(self, auth_settings: Settings) -> None:
        expired_settings = Settings(
            jwt_secret_key=auth_settings.jwt_secret_key,
            jwt_access_token_expire_minutes=0,  # Expires immediately
            app_env="testing",
        )
        token = create_access_token(
            user_id="user-123",
            email="test@example.com",
            settings=expired_settings,
        )
        # Small delay to ensure expiry
        time.sleep(0.1)
        with pytest.raises(AuthenticationError, match="expired"):
            decode_access_token(token, expired_settings)

    def test_invalid_token_raises(self, auth_settings: Settings) -> None:
        with pytest.raises(AuthenticationError, match="Invalid"):
            decode_access_token("not.a.valid.token", auth_settings)

    def test_wrong_secret_raises(self, auth_settings: Settings) -> None:
        token = create_access_token(
            user_id="user-123",
            email="test@example.com",
            settings=auth_settings,
        )
        wrong_secret_settings = Settings(
            jwt_secret_key="different-secret-key",
            app_env="testing",
        )
        with pytest.raises(AuthenticationError):
            decode_access_token(token, wrong_secret_settings)

    def test_token_contains_type(self, auth_settings: Settings) -> None:
        import jwt as pyjwt

        token = create_access_token(
            user_id="user-123",
            email="test@example.com",
            settings=auth_settings,
        )
        raw = pyjwt.decode(
            token,
            auth_settings.jwt_secret_key,
            algorithms=[auth_settings.jwt_algorithm],
        )
        assert raw["type"] == "access"


# ── Refresh Tokens ───────────────────────────────────────────


class TestRefreshTokens:
    def test_generate_produces_unique_tokens(self, auth_settings: Settings) -> None:
        token1, _, _ = generate_refresh_token(auth_settings)
        token2, _, _ = generate_refresh_token(auth_settings)
        assert token1 != token2

    def test_hash_matches(self, auth_settings: Settings) -> None:
        raw_token, stored_hash, _ = generate_refresh_token(auth_settings)
        assert hash_refresh_token(raw_token) == stored_hash

    def test_wrong_token_does_not_match(self, auth_settings: Settings) -> None:
        _, stored_hash, _ = generate_refresh_token(auth_settings)
        assert hash_refresh_token("wrong-token") != stored_hash

    def test_expiry_is_in_future(self, auth_settings: Settings) -> None:
        from datetime import datetime

        _, _, expires_at = generate_refresh_token(auth_settings)
        assert expires_at > datetime.now(UTC)


# ── API Keys ─────────────────────────────────────────────────


class TestAPIKeys:
    def test_generate_and_verify(self) -> None:
        full_key, prefix, key_hash = generate_api_key()
        assert verify_api_key(full_key, key_hash) is True

    def test_key_starts_with_prefix(self) -> None:
        full_key, prefix, _ = generate_api_key()
        assert full_key.startswith("sk-")
        assert prefix == full_key[:12]

    def test_wrong_key_fails_verification(self) -> None:
        _, _, key_hash = generate_api_key()
        assert verify_api_key("sk-wrong-key", key_hash) is False

    def test_unique_keys(self) -> None:
        key1, _, _ = generate_api_key()
        key2, _, _ = generate_api_key()
        assert key1 != key2

    def test_verify_with_invalid_hash_returns_false(self) -> None:
        assert verify_api_key("sk-some-key", "not-a-hash") is False

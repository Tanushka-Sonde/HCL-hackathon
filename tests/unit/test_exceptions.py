"""Unit tests for src.core.exceptions."""

from __future__ import annotations

from src.core.exceptions import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_app_error(self) -> None:
        exceptions = [
            NotFoundError("Doc", "123"),
            ConflictError(),
            AuthenticationError(),
            AuthorizationError(),
            RateLimitError(),
            ValidationError(),
            ExternalServiceError("Gemini"),
        ]
        for exc in exceptions:
            assert isinstance(exc, AppError)

    def test_not_found_error(self) -> None:
        exc = NotFoundError("Document", "abc-123")
        assert exc.status_code == 404
        assert exc.code == "NOT_FOUND"
        assert "abc-123" in exc.message
        assert "Document" in exc.message

    def test_conflict_error(self) -> None:
        exc = ConflictError("Duplicate email.")
        assert exc.status_code == 409
        assert exc.code == "CONFLICT"
        assert exc.message == "Duplicate email."

    def test_authentication_error(self) -> None:
        exc = AuthenticationError()
        assert exc.status_code == 401
        assert exc.code == "AUTHENTICATION_FAILED"

    def test_authorization_error(self) -> None:
        exc = AuthorizationError()
        assert exc.status_code == 403
        assert exc.code == "FORBIDDEN"

    def test_rate_limit_error(self) -> None:
        exc = RateLimitError()
        assert exc.status_code == 429

    def test_validation_error(self) -> None:
        exc = ValidationError("Bad input.")
        assert exc.status_code == 422
        assert exc.message == "Bad input."

    def test_external_service_error(self) -> None:
        exc = ExternalServiceError("Gemini", "timeout")
        assert exc.status_code == 502
        assert "Gemini" in exc.message
        assert "timeout" in exc.message

    def test_external_service_error_without_detail(self) -> None:
        exc = ExternalServiceError("Tavily")
        assert "Tavily" in exc.message
        assert exc.code == "EXTERNAL_SERVICE_ERROR"

    def test_app_error_is_catchable(self) -> None:
        try:
            raise NotFoundError("User", "999")
        except AppError as exc:
            assert exc.status_code == 404

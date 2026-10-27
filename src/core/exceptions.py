"""Application exception hierarchy.

Every exception carries a machine-readable ``code`` for API error responses
and an HTTP ``status_code`` for the response status line.  The FastAPI error
handler maps these to a standard JSON envelope.
"""

from __future__ import annotations


class AppError(Exception):
    """Base exception for all application errors."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(self, message: str = "An internal error occurred.") -> None:
        self.message = message
        super().__init__(self.message)


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    code = "NOT_FOUND"
    status_code = 404

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} with identifier '{identifier}' not found.")


class ConflictError(AppError):
    """Raised on duplicate resource creation or constraint violation."""

    code = "CONFLICT"
    status_code = 409

    def __init__(self, message: str = "Resource already exists.") -> None:
        super().__init__(message)


class AuthenticationError(AppError):
    """Raised when credentials are missing, invalid, or expired."""

    code = "AUTHENTICATION_FAILED"
    status_code = 401

    def __init__(self, message: str = "Invalid or expired credentials.") -> None:
        super().__init__(message)


class AuthorizationError(AppError):
    """Raised when the user lacks permission for the requested action."""

    code = "FORBIDDEN"
    status_code = 403

    def __init__(self, message: str = "Insufficient permissions.") -> None:
        super().__init__(message)


class RateLimitError(AppError):
    """Raised when a rate limit is exceeded."""

    code = "RATE_LIMITED"
    status_code = 429

    def __init__(self, message: str = "Rate limit exceeded. Try again later.") -> None:
        super().__init__(message)


class ValidationError(AppError):
    """Raised for application-level validation failures.

    Distinct from Pydantic's ``ValidationError`` which handles
    request schema validation automatically via FastAPI.
    """

    code = "VALIDATION_ERROR"
    status_code = 422

    def __init__(self, message: str = "Request validation failed.") -> None:
        super().__init__(message)


class ExternalServiceError(AppError):
    """Raised when a third-party API (Gemini, Tavily, MinIO) is unavailable."""

    code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502

    def __init__(self, service: str, message: str = "") -> None:
        detail = f"External service '{service}' is unavailable."
        if message:
            detail = f"{detail} {message}"
        super().__init__(detail)

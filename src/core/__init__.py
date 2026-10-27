"""Core infrastructure package.

Provides configuration, database, security, logging, pagination,
and the exception hierarchy used by all other packages.
"""

from src.core.config import Settings, get_settings
from src.core.database import Base, Database
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
from src.core.logging import configure_logging, get_logger
from src.core.pagination import (
    PaginatedResponse,
    decode_cursor,
    encode_cursor,
)
from src.core.security import (
    TokenPayload,
    create_access_token,
    decode_access_token,
    generate_api_key,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_api_key,
    verify_password,
)

__all__ = [
    # config
    "Settings",
    "get_settings",
    # database
    "Base",
    "Database",
    # exceptions
    "AppError",
    "AuthenticationError",
    "AuthorizationError",
    "ConflictError",
    "ExternalServiceError",
    "NotFoundError",
    "RateLimitError",
    "ValidationError",
    # logging
    "configure_logging",
    "get_logger",
    # pagination
    "PaginatedResponse",
    "decode_cursor",
    "encode_cursor",
    # security
    "TokenPayload",
    "create_access_token",
    "decode_access_token",
    "generate_api_key",
    "generate_refresh_token",
    "hash_password",
    "hash_refresh_token",
    "verify_api_key",
    "verify_password",
]

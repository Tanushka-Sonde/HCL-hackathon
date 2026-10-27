"""Cursor-based pagination utilities.

Cursors are base64-encoded JSON payloads containing the last-seen sort key.
This provides O(1) page retrieval regardless of dataset size, unlike
offset-based pagination which is O(offset).
"""

from __future__ import annotations

import base64
import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

_ENCODING = "utf-8"


def encode_cursor(data: dict[str, Any]) -> str:
    """Encode pagination state into an opaque cursor string.

    Args:
        data: Dictionary with sort-key values (e.g. ``{"id": "abc-123"}``).

    Returns:
        URL-safe base64 string.
    """
    json_bytes = json.dumps(data, sort_keys=True, default=str).encode(_ENCODING)
    return base64.urlsafe_b64encode(json_bytes).decode(_ENCODING)


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode an opaque cursor string into pagination state.

    Args:
        cursor: Base64 string previously returned by ``encode_cursor``.

    Returns:
        Dictionary with sort-key values.

    Raises:
        ValueError: If the cursor is malformed or tampered with.
    """
    try:
        json_bytes = base64.urlsafe_b64decode(cursor.encode(_ENCODING))
        data: dict[str, Any] = json.loads(json_bytes)
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Pagination cursor must encode a JSON object.")

    return data


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response envelope.

    All list endpoints return this shape, enabling clients to iterate
    through results with stable, stateless cursors.
    """

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False

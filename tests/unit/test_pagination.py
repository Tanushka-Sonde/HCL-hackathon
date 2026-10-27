"""Unit tests for src.core.pagination."""

from __future__ import annotations

import pytest

from src.core.pagination import (
    PaginatedResponse,
    decode_cursor,
    encode_cursor,
)


class TestCursorEncoding:
    def test_roundtrip(self) -> None:
        data = {"id": "abc-123", "created_at": "2026-01-01T00:00:00Z"}
        cursor = encode_cursor(data)
        decoded = decode_cursor(cursor)
        assert decoded == data

    def test_cursor_is_url_safe(self) -> None:
        data = {"id": "test/with+special=chars"}
        cursor = encode_cursor(data)
        # URL-safe base64 uses - and _ instead of + and /
        assert "+" not in cursor
        assert "/" not in cursor

    def test_decode_invalid_cursor_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor("not-valid-base64!!!")

    def test_decode_non_dict_raises(self) -> None:
        import base64
        import json

        bad_cursor = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).decode()
        with pytest.raises(ValueError, match="JSON object"):
            decode_cursor(bad_cursor)

    def test_empty_dict_roundtrip(self) -> None:
        cursor = encode_cursor({})
        assert decode_cursor(cursor) == {}

    def test_uuid_serialization(self) -> None:
        import uuid

        uid = uuid.uuid4()
        cursor = encode_cursor({"id": uid})
        decoded = decode_cursor(cursor)
        assert decoded["id"] == str(uid)


class TestPaginatedResponse:
    def test_empty_response(self) -> None:
        resp = PaginatedResponse[str](items=[], has_more=False)
        assert resp.items == []
        assert resp.next_cursor is None
        assert resp.has_more is False

    def test_with_items_and_cursor(self) -> None:
        resp = PaginatedResponse[str](
            items=["a", "b"],
            next_cursor="abc123",
            has_more=True,
        )
        assert len(resp.items) == 2
        assert resp.next_cursor == "abc123"
        assert resp.has_more is True

    def test_serialization(self) -> None:
        resp = PaginatedResponse[int](
            items=[1, 2, 3],
            next_cursor="cursor",
            has_more=True,
        )
        data = resp.model_dump()
        assert data["items"] == [1, 2, 3]
        assert data["next_cursor"] == "cursor"
        assert data["has_more"] is True

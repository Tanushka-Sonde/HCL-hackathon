"""Authentication and role enforcement (WP-1).

Security is enforced by the API, so these tests call it directly instead of
relying on what the UI hides.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from src.knowledge.service import KnowledgeService

NO_AUTH = {"Authorization": ""}

ADMIN_ROUTES = [
    ("get", "/api/v1/kis/documents", None),
    ("post", "/api/v1/kis/ingest/demo", None),
    ("delete", "/api/v1/kis/documents/some-id", None),
    ("get", "/api/v1/kis/metrics", None),
    ("get", "/api/v1/kis/queries", None),
    ("get", "/api/v1/kis/queries/some-id", None),
    ("post", "/api/v1/kis/eval/run", {"configs": ["A"]}),
    ("get", "/api/v1/kis/eval/status", None),
    ("get", "/api/v1/kis/admin/users", None),
    ("post", "/api/v1/kis/admin/users", {"username": "eve", "password": "secret1"}),
]


def _call(client: TestClient, method: str, path: str, body, headers):
    if body is None:
        return getattr(client, method)(path, headers=headers)
    return getattr(client, method)(path, json=body, headers=headers)


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_user_gets_403_on_admin_routes(
    client: TestClient, user_headers: dict, method: str, path: str, body
) -> None:
    assert _call(client, method, path, body, user_headers).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_anonymous_gets_401(client: TestClient, method: str, path: str, body) -> None:
    assert _call(client, method, path, body, NO_AUTH).status_code == 401


def test_user_ingest_is_forbidden_and_logged(
    client: TestClient, user_headers: dict, service: KnowledgeService
) -> None:
    resp = client.post(
        "/api/v1/kis/ingest",
        files={"file": ("x.txt", b"Doc-ID: X-1\nSome text here.", "text/plain")},
        headers=user_headers,
    )
    assert resp.status_code == 403
    forbidden = [
        e
        for e in service.store.list_auth_events()
        if e["event"] == "forbidden" and e["detail"] == "/api/v1/kis/ingest"
    ]
    assert forbidden and forbidden[-1]["username"] == "alice"


def test_login_success_failure_and_logging(
    client: TestClient, service: KnowledgeService
) -> None:
    bad = client.post(
        "/api/v1/kis/auth/login", json={"username": "alice", "password": "nope"}
    )
    unknown = client.post(
        "/api/v1/kis/auth/login", json={"username": "ghost", "password": "nope"}
    )
    # Same message whether the user exists or not.
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()
    ok = client.post(
        "/api/v1/kis/auth/login", json={"username": "Alice", "password": "user123"}
    )
    assert ok.status_code == 200 and ok.json()["role"] == "user"
    events = {e["event"] for e in service.store.list_auth_events()}
    assert {"login", "login_failed"} <= events


def test_tampered_token_rejected(client: TestClient, user_headers: dict) -> None:
    token = user_headers["Authorization"] + "x"
    resp = client.get("/api/v1/kis/auth/me", headers={"Authorization": token})
    assert resp.status_code == 401


def test_user_can_query_and_rate_own_answer_only(
    client: TestClient, user_headers: dict, bob_headers: dict
) -> None:
    resp = client.post(
        "/api/v1/kis/query",
        json={"query": "Who must approve ACR-3310?"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    qid = resp.json()["query_id"]
    mine = client.post(
        "/api/v1/kis/feedback",
        json={"query_id": qid, "helpful": True},
        headers=user_headers,
    )
    theirs = client.post(
        "/api/v1/kis/feedback",
        json={"query_id": qid, "helpful": False},
        headers=bob_headers,
    )
    assert mine.status_code == 200 and theirs.status_code == 404
    event = client.get(f"/api/v1/kis/queries/{qid}").json()  # as admin
    assert event["identity"]["username"] == "alice"


def test_session_cannot_be_hijacked(
    client: TestClient, user_headers: dict, bob_headers: dict
) -> None:
    first = client.post(
        "/api/v1/kis/query",
        json={
            "query": "What is the per diem for domestic travel?",
            "session_id": "s-own",
        },
        headers=user_headers,
    )
    assert first.status_code == 200
    hijack = client.post(
        "/api/v1/kis/query",
        json={"query": "And what about international?", "session_id": "s-own"},
        headers=bob_headers,
    )
    assert hijack.status_code == 403


def test_admin_creates_user_who_can_log_in(client: TestClient) -> None:
    created = client.post(
        "/api/v1/kis/admin/users",
        json={"username": "carol", "password": "carol123", "role": "user"},
    )
    assert created.status_code == 201 and created.json()["role"] == "user"
    dup = client.post(
        "/api/v1/kis/admin/users", json={"username": "carol", "password": "xxxxxx"}
    )
    assert dup.status_code == 409
    login = client.post(
        "/api/v1/kis/auth/login", json={"username": "carol", "password": "carol123"}
    )
    assert login.status_code == 200


def test_no_response_contains_a_password(
    client: TestClient, user_headers: dict
) -> None:
    bodies = [
        client.get("/api/v1/kis/admin/users").json(),
        client.get("/api/v1/kis/auth/me").json(),
        client.get("/api/v1/kis/auth/me", headers=user_headers).json(),
        client.post(
            "/api/v1/kis/auth/login", json={"username": "admin", "password": "admin123"}
        ).json(),
        client.get("/api/v1/kis/queries").json(),
        client.get("/api/v1/kis/metrics").json(),
    ]
    for body in bodies:
        assert "password" not in json.dumps(body).lower()

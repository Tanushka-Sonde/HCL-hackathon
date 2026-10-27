"""Role-based masking of personal data and salaries (WP-4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

QUESTION = "What is the annual salary and email of Tom Becker?"


def _ask(client: TestClient, headers: dict | None = None) -> dict:
    kwargs = {"headers": headers} if headers else {}
    resp = client.post("/api/v1/kis/query", json={"query": QUESTION}, **kwargs)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_user_sees_masked_values(client: TestClient, user_headers: dict) -> None:
    body = _ask(client, user_headers)
    assert "[SALARY]" in body["answer"] and "121,500" not in body["answer"]
    assert "@orion-synthetic.example" not in body["answer"]
    for ev in body["evidence"]:
        assert "121,500" not in ev["content"]
        assert "@orion-synthetic.example" not in ev["content"]
    assert "PII_MASKED" in body["flags"]
    assert body["safety"]["pii_masked"].get("salary")
    assert body["safety"]["pii_detected"] is None  # not shown to users


def test_admin_sees_raw_values(client: TestClient) -> None:
    body = _ask(client)
    assert "121,500" in body["answer"]
    assert "PII_MASKED" not in body["flags"]
    assert body["safety"]["pii_detected"]["answer"].get("salary")


def test_masking_does_not_change_grounding(
    client: TestClient, user_headers: dict
) -> None:
    user = _ask(client, user_headers)
    admin = _ask(client)
    assert user["grounding_score"] == admin["grounding_score"]
    assert user["outcome"] == admin["outcome"]
    assert [c["valid"] for c in user["citations"]] == [
        c["valid"] for c in admin["citations"]
    ]


def test_event_keeps_raw_answer_for_admin(
    client: TestClient, user_headers: dict
) -> None:
    body = _ask(client, user_headers)
    event = client.get(f"/api/v1/kis/queries/{body['query_id']}").json()
    assert "121,500" in event["generation"]["output"]
    assert event["masking"]["applied"] is True
    assert event["masking"]["counts"].get("salary")


def test_answer_is_about_the_asked_person_only(client: TestClient) -> None:
    body = _ask(client)
    assert "Tom Becker" in body["answer"] and "Asha Rao" not in body["answer"]

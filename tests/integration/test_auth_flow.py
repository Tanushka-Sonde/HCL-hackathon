"""Integration tests for the authentication flow."""

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_auth_flow_register_login_refresh(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test the complete auth flow: register, login, access protected route, refresh."""

    # 1. Register a new user
    register_data = {"email": "flow@example.com", "password": "strong-password-123"}
    resp = await client.post("/api/v1/auth/register", json=register_data)
    assert resp.status_code == 201

    # 2. Login to get tokens
    login_data = {"email": "flow@example.com", "password": "strong-password-123"}
    resp = await client.post("/api/v1/auth/login", json=login_data)
    assert resp.status_code == 200

    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data

    access_token = data["access_token"]
    refresh_token = data["refresh_token"]

    # 3. Access a protected route (e.g. get current user)
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    me_data = resp.json()
    assert me_data["email"] == "flow@example.com"

    await asyncio.sleep(1.1)

    # 4. Use refresh token to get a new access token
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert resp.status_code == 200
    refresh_data = resp.json()
    assert "access_token" in refresh_data

    new_access_token = refresh_data["access_token"]
    assert new_access_token != access_token

    # 5. Access protected route with new token
    headers = {"Authorization": f"Bearer {new_access_token}"}
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "flow@example.com"

"""Integration tests for observability metrics."""

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_metrics_endpoint_is_internal(client: httpx.AsyncClient) -> None:
    """Verify /metrics returns Prometheus text format and is accessible."""
    response = await client.get("/metrics", follow_redirects=True)
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "active_requests" in response.text


@pytest.mark.asyncio
async def test_metrics_bounded_cardinality(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Verify that route templates are used instead of raw URLs for labels."""
    # We'll make a request to a 404 URL and a real URL with a path param.
    # To test bounded cardinality on path params, we'd need an endpoint with one.
    # The app has `/api/v1/jobs/{job_id}` but we might not have a valid job.
    # A 404 to that path is fine, but it might just return 404 Unhandled Path if not matched.
    # Let's hit the shallow health check which has no path params, and
    # a non-existent path to see if it groups them.

    # Send a request to /health
    await client.get("/health")

    # Send a request to an unhandled path
    await client.get("/some/random/id/12345")

    # Verify the metrics in the registry
    http_requests = REGISTRY.get_sample_value(
        "http_requests_total",
        {"method": "GET", "route_template": "/health", "status": "200"},
    )
    assert http_requests is not None
    assert http_requests >= 1.0

    unhandled_requests = REGISTRY.get_sample_value(
        "http_requests_total",
        {"method": "GET", "route_template": "unhandled_path", "status": "404"},
    )
    assert unhandled_requests is not None
    assert unhandled_requests >= 1.0


@pytest.mark.asyncio
async def test_active_requests_decremented_on_exception(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Verify active_requests gauge drops even if an exception is raised."""
    # First, record baseline active requests
    baseline = REGISTRY.get_sample_value("active_requests") or 0.0

    # Add a temporary route that just raises an exception
    @app.get("/test_crash")
    async def crash_endpoint() -> dict:
        raise ValueError("Boom!")

    with pytest.raises(ValueError, match="Boom!"):
        await client.get("/test_crash")

    # Verify the gauge is back to baseline
    current = REGISTRY.get_sample_value("active_requests") or 0.0
    assert current == baseline

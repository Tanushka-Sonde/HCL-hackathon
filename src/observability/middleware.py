"""FastAPI middleware for Prometheus metrics collection."""

import re
import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.observability.metrics import (
    active_requests,
    http_request_duration_seconds,
    http_requests_total,
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP metrics with bounded cardinality."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Fast path to skip metrics on the metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        active_requests.inc()
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            active_requests.dec()
            duration = time.perf_counter() - start_time

            # Extract bounded route template to prevent cardinality explosion
            route_template = self._get_route_template(request)

            http_requests_total.labels(
                method=method,
                route_template=route_template,
                status=status_code,
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                route_template=route_template,
            ).observe(duration)

    def _get_route_template(self, request: Request) -> str:
        """Extract the FastAPI route template (e.g., /jobs/{job_id})."""
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            return route.path
        return "unhandled_path"


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request/correlation ID to every request and response.

    Honors a well-formed incoming ``X-Request-ID``; otherwise generates one.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

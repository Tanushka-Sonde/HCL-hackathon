"""Prometheus metrics registry."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── HTTP Metrics ─────────────────────────────────────────────────────────────

# Use route_template instead of raw path for bounded cardinality.
http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    labelnames=["method", "route_template", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=["method", "route_template"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
)

active_requests = Gauge(
    "active_requests",
    "Number of currently inflight HTTP requests",
)

# ── LLM Gateway Metrics ──────────────────────────────────────────────────────

llm_requests_total = Counter(
    "llm_requests_total",
    "Total number of LLM requests",
    # Bounded cardinality: provider (e.g. gemini), operation (e.g. evaluate_relevance), outcome (success/error/timeout)
    labelnames=["provider", "operation", "outcome"],
)

llm_circuit_breaker_state = Gauge(
    "llm_circuit_breaker_state",
    "Current state of the LLM circuit breaker (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
)

# ── Database Metrics ─────────────────────────────────────────────────────────

db_pool_size = Gauge(
    "db_pool_size",
    "Configured SQLAlchemy connection pool size",
)

db_pool_checkedout = Gauge(
    "db_pool_checkedout",
    "Number of currently checked out database connections",
)

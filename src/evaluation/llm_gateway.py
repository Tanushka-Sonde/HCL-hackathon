"""LLM gateway with rate limiting, retry, concurrency bounding, and circuit breaker.

Implements ADR-004 (token bucket + semaphore) and ADR-009 (in-process circuit breaker).

Usage::

    gateway = LLMGateway(settings)
    response = await gateway.complete("Grade this document for relevance.")

Architecture:
    1. Token bucket (aiolimiter) — enforces RPM limit.
    2. Semaphore — bounds concurrent in-flight calls.
    3. Circuit breaker — fast-fails during sustained outages.
    4. Tenacity retry — handles transient errors with exponential backoff.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.exceptions import ExternalServiceError
from src.core.logging import get_logger
from src.observability.metrics import (
    llm_circuit_breaker_state,
    llm_requests_total,
)

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)


# ── Circuit Breaker ──────────────────────────────────────────


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Fast-fail (API is down)
    HALF_OPEN = "half_open"  # Probing (one request allowed)


@dataclass
class CircuitBreaker:
    """In-process circuit breaker for external API calls.

    State machine:
        CLOSED → OPEN: after ``failure_threshold`` consecutive failures.
        OPEN → HALF_OPEN: after ``recovery_timeout`` seconds.
        HALF_OPEN → CLOSED: on first success.
        HALF_OPEN → OPEN: on first failure.

    State resets on process restart, which is acceptable per ADR-009:
    external API health is quickly re-discovered within a few failed calls.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0

    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    failure_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def check(self) -> None:
        """Check whether the circuit allows a request.

        Raises:
            ExternalServiceError: If the circuit is OPEN.
        """
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return

            if self.state == CircuitState.OPEN:
                elapsed = time.monotonic() - self.last_failure_time
                if elapsed >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    llm_circuit_breaker_state.set(1)
                    logger.info(
                        "circuit_half_open",
                        elapsed_seconds=round(elapsed, 1),
                    )
                    return
                raise ExternalServiceError(
                    "LLM",
                    f"Circuit breaker is OPEN. Retry after "
                    f"{round(self.recovery_timeout - elapsed)}s.",
                )

            # HALF_OPEN — allow the probe request
            return

    async def record_success(self) -> None:
        """Record a successful API call."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                logger.info("circuit_closed", reason="probe_success")
            self.failure_count = 0
            self.state = CircuitState.CLOSED
            llm_circuit_breaker_state.set(0)

    async def record_failure(self) -> None:
        """Record a failed API call."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()

            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                llm_circuit_breaker_state.set(2)
                logger.warning(
                    "circuit_opened",
                    reason="probe_failed",
                )
            elif self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                llm_circuit_breaker_state.set(2)
                logger.warning(
                    "circuit_opened",
                    failure_count=self.failure_count,
                    threshold=self.failure_threshold,
                )


# ── LLM Gateway ──────────────────────────────────────────────


class LLMGateway:
    """Rate-limited, retry-capable, circuit-broken LLM client.

    Wraps Google Gemini (via ``google-generativeai``) with:
    - Token bucket rate limiting (``aiolimiter``)
    - Concurrency semaphore (``asyncio.Semaphore``)
    - Exponential backoff retry (``tenacity``)
    - In-process circuit breaker
    """

    def __init__(self, settings: Settings) -> None:
        self._model_name = settings.llm_model_name
        self._api_key = settings.google_api_key
        self._timeout = settings.llm_timeout_seconds
        self._max_retries = settings.llm_max_retries

        # ADR-004: Token bucket for RPM + semaphore for concurrency
        self._rate_limiter = AsyncLimiter(settings.llm_rate_limit_rpm, 60)
        self._semaphore = asyncio.Semaphore(settings.llm_concurrency_limit)

        # ADR-009: In-process circuit breaker
        self._circuit = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
        )

        self._client: object | None = None

    def _get_client(self) -> object:
        """Lazy-initialize the Gemini client."""
        if self._client is None:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(self._model_name)
            logger.info("llm_client_initialized", model=self._model_name)
        return self._client

    async def complete(self, prompt: str, operation: str = "completion") -> str:
        """Send a prompt to the LLM and return the response text.

        Flow:
            1. Circuit breaker check (fast-fail if OPEN).
            2. Token bucket acquire (blocks until RPM allows).
            3. Semaphore acquire (bounds concurrency).
            4. Retry with exponential backoff on transient errors.
            5. Record success/failure for circuit breaker.

        Args:
            prompt: The text prompt to send.

        Returns:
            The model's response text.

        Raises:
            ExternalServiceError: If the LLM is unreachable after retries.
            RateLimitError: If rate limit cannot be acquired.
        """
        await self._circuit.check()
        await self._rate_limiter.acquire()

        async with self._semaphore:
            try:
                result = await self._call_with_retry(prompt)
                await self._circuit.record_success()
                llm_requests_total.labels(
                    provider="gemini", operation=operation, outcome="success"
                ).inc()
                return result
            except Exception as exc:
                await self._circuit.record_failure()
                llm_requests_total.labels(
                    provider="gemini", operation=operation, outcome="error"
                ).inc()
                raise ExternalServiceError("LLM", str(exc)) from exc

    async def _call_with_retry(self, prompt: str) -> str:
        """Execute the LLM call with tenacity retry."""

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        async def _inner() -> str:
            client = self._get_client()
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.generate_content,
                    prompt,  # type: ignore[union-attr]
                ),
                timeout=self._timeout,
            )
            text = response.text  # type: ignore[union-attr]
            if not text:
                raise ExternalServiceError("LLM", "Empty response from model.")
            return text  # type: ignore[no-any-return]

        return await _inner()

    @property
    def circuit_state(self) -> str:
        """Return the current circuit breaker state (for health checks)."""
        return self._circuit.state.value

"""Unit tests for LLM gateway: circuit breaker, grade parsing, schemas.

No real LLM calls are made. All external interactions are mocked.
"""

from __future__ import annotations

import asyncio

import pytest

from src.core.config import Settings
from src.core.exceptions import ExternalServiceError
from src.evaluation.llm_gateway import CircuitBreaker, CircuitState, LLMGateway
from src.evaluation.schemas import RelevanceGrade, RelevanceRequest
from src.evaluation.service import _parse_grade

# ── Circuit Breaker ──────────────────────────────────────────


class TestCircuitBreaker:
    @pytest.fixture
    def breaker(self) -> CircuitBreaker:
        return CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)

    async def test_starts_closed(self, breaker: CircuitBreaker) -> None:
        assert breaker.state == CircuitState.CLOSED

    async def test_stays_closed_below_threshold(self, breaker: CircuitBreaker) -> None:
        await breaker.record_failure()
        await breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

    async def test_opens_at_threshold(self, breaker: CircuitBreaker) -> None:
        for _ in range(3):
            await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    async def test_open_rejects_requests(self, breaker: CircuitBreaker) -> None:
        for _ in range(3):
            await breaker.record_failure()

        from src.core.exceptions import ExternalServiceError

        with pytest.raises(ExternalServiceError, match="OPEN"):
            await breaker.check()

    async def test_transitions_to_half_open_after_timeout(
        self, breaker: CircuitBreaker
    ) -> None:
        for _ in range(3):
            await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)
        await breaker.check()  # Should not raise
        assert breaker.state == CircuitState.HALF_OPEN

    async def test_half_open_closes_on_success(self, breaker: CircuitBreaker) -> None:
        for _ in range(3):
            await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.check()  # Transition to HALF_OPEN

        await breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    async def test_half_open_reopens_on_failure(self, breaker: CircuitBreaker) -> None:
        for _ in range(3):
            await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.check()  # Transition to HALF_OPEN

        await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    async def test_success_resets_failure_count(self, breaker: CircuitBreaker) -> None:
        await breaker.record_failure()
        await breaker.record_failure()
        await breaker.record_success()
        assert breaker.failure_count == 0
        # Should not open now — counter was reset
        await breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED


class TestLLMGatewayOutage:
    async def test_repeated_outages_open_circuit(
        self,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        gateway = LLMGateway(settings)
        gateway._circuit = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=60.0,
        )
        calls = 0

        async def fail_call(prompt: str) -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr(gateway, "_call_with_retry", fail_call)

        with pytest.raises(ExternalServiceError, match="provider unavailable"):
            await gateway.complete("grade this")
        with pytest.raises(ExternalServiceError, match="provider unavailable"):
            await gateway.complete("grade this")

        assert gateway.circuit_state == CircuitState.OPEN.value

        with pytest.raises(ExternalServiceError, match="OPEN"):
            await gateway.complete("grade this")
        assert calls == 2


# ── Grade Parsing ────────────────────────────────────────────


class TestGradeParsing:
    def test_parse_relevant(self) -> None:
        grade, reasoning = _parse_grade("relevant|The chunk answers the query.")
        assert grade == RelevanceGrade.RELEVANT
        assert reasoning == "The chunk answers the query."

    def test_parse_not_relevant(self) -> None:
        grade, reasoning = _parse_grade("not_relevant|Off topic.")
        assert grade == RelevanceGrade.NOT_RELEVANT
        assert reasoning == "Off topic."

    def test_parse_ambiguous(self) -> None:
        grade, reasoning = _parse_grade("ambiguous|Partially related.")
        assert grade == RelevanceGrade.AMBIGUOUS
        assert reasoning == "Partially related."

    def test_parse_no_pipe(self) -> None:
        """Grade without pipe separator extracts grade with empty reasoning."""
        grade, reasoning = _parse_grade("relevant")
        assert grade == RelevanceGrade.RELEVANT
        assert reasoning == ""

    def test_parse_case_insensitive(self) -> None:
        grade, _ = _parse_grade("RELEVANT|yes")
        assert grade == RelevanceGrade.RELEVANT

    def test_parse_unknown_falls_back_to_ambiguous(self) -> None:
        grade, reasoning = _parse_grade("maybe|unsure about this")
        assert grade == RelevanceGrade.AMBIGUOUS
        assert "Could not parse" in reasoning

    def test_parse_empty_response(self) -> None:
        grade, _reasoning = _parse_grade("")
        assert grade == RelevanceGrade.AMBIGUOUS

    def test_parse_with_leading_whitespace(self) -> None:
        grade, _ = _parse_grade("  relevant|yes")
        assert grade == RelevanceGrade.RELEVANT


# ── Schemas ──────────────────────────────────────────────────


class TestRelevanceRequest:
    def test_valid_request(self) -> None:
        import uuid

        req = RelevanceRequest(
            query="What is machine learning?",
            chunk_ids=[uuid.uuid4(), uuid.uuid4()],
        )
        assert len(req.chunk_ids) == 2

    def test_empty_query_rejected(self) -> None:
        import uuid

        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="at least 1"):
            RelevanceRequest(query="", chunk_ids=[uuid.uuid4()])

    def test_empty_chunk_ids_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="at least 1"):
            RelevanceRequest(query="test", chunk_ids=[])

    def test_too_many_chunk_ids_rejected(self) -> None:
        import uuid

        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="at most 20"):
            RelevanceRequest(
                query="test",
                chunk_ids=[uuid.uuid4() for _ in range(21)],
            )

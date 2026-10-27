"""Evaluation service: CRAG relevance grading.

Evaluates whether retrieved chunks are relevant to a user's query
using an LLM as a judge (Gemini via the LLM gateway).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.core.logging import get_logger
from src.evaluation.llm_gateway import LLMGateway
from src.evaluation.schemas import ChunkRelevance, RelevanceGrade
from src.ingestion.models import Chunk

logger = get_logger(__name__)

# Structured prompt for CRAG-style relevance grading.
# The LLM must respond with exactly one of: relevant, ambiguous, not_relevant.
_GRADING_PROMPT = """You are a relevance grading system. Your job is to evaluate whether a document chunk is relevant to a user's query.

Query: {query}

Chunk content:
---
{content}
---

Grade the relevance of the chunk to the query. Respond with EXACTLY one of these three words followed by a pipe and a brief reasoning:

relevant|<reasoning>
ambiguous|<reasoning>
not_relevant|<reasoning>

Rules:
- "relevant" means the chunk directly answers or is clearly useful for the query.
- "ambiguous" means the chunk is partially related but may not fully answer the query.
- "not_relevant" means the chunk has no meaningful connection to the query.
- Your response must start with the grade, followed by a pipe character, followed by reasoning.
- Do not include any other text.
"""


def _parse_grade(response: str) -> tuple[RelevanceGrade, str]:
    """Parse the LLM's grading response into a grade and reasoning.

    Expected format: ``relevant|The chunk discusses...``
    """
    response = response.strip()

    for grade in RelevanceGrade:
        if response.lower().startswith(grade.value):
            parts = response.split("|", 1)
            reasoning = parts[1].strip() if len(parts) > 1 else ""
            return grade, reasoning

    # Fallback: if the LLM doesn't follow format, treat as ambiguous
    logger.warning("unparseable_grade", raw_response=response[:200])
    return RelevanceGrade.AMBIGUOUS, f"Could not parse LLM response: {response[:100]}"


async def evaluate_relevance(
    query: str,
    chunk_ids: list[uuid.UUID],
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    gateway: LLMGateway,
) -> list[ChunkRelevance]:
    """Evaluate relevance of specific chunks against a query.

    Args:
        query: The user's search query.
        chunk_ids: IDs of chunks to evaluate.
        user_id: The current user (for authorization).
        db: Async database session.
        gateway: LLM gateway with rate limiting and circuit breaker.

    Returns:
        List of ChunkRelevance evaluations.

    Raises:
        NotFoundError: If any chunk_id does not exist for this user.
    """
    # Load chunks, scoped to user
    result = await db.execute(
        select(Chunk).where(
            Chunk.id.in_(chunk_ids),
            Chunk.tenant_id == tenant_id,
        )
    )
    chunks = {c.id: c for c in result.scalars().all()}

    # Verify all requested chunks exist
    for cid in chunk_ids:
        if cid not in chunks:
            raise NotFoundError("Chunk", str(cid))

    # Grade each chunk via LLM
    evaluations: list[ChunkRelevance] = []
    for cid in chunk_ids:
        chunk = chunks[cid]
        prompt = _GRADING_PROMPT.format(
            query=query,
            content=chunk.content[:2000],  # Truncate to avoid token limits
        )

        try:
            response = await gateway.complete(prompt)
            grade, reasoning = _parse_grade(response)
        except Exception as exc:
            logger.warning(
                "grading_failed",
                chunk_id=str(cid),
                error=str(exc),
            )
            grade = RelevanceGrade.AMBIGUOUS
            reasoning = f"Evaluation failed: {exc}"

        evaluations.append(
            ChunkRelevance(
                chunk_id=cid,
                grade=grade,
                reasoning=reasoning,
            )
        )

    logger.info(
        "relevance_evaluated",
        query_length=len(query),
        chunk_count=len(evaluations),
        grades={
            g.value: sum(1 for e in evaluations if e.grade == g) for g in RelevanceGrade
        },
    )
    return evaluations

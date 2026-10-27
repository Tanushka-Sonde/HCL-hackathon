"""Hybrid retrieval service: pgvector (dense) + tsvector (sparse) + RRF.

This implements the core search pipeline:

1. Dense retrieval: Embed the query, then ``ORDER BY embedding <=> query_vec``
   using the HNSW index on the ``chunks`` table.
2. Sparse retrieval: Convert the query to a tsquery, then rank with
   ``ts_rank_cd`` using the GIN index on the ``tsv`` column.
3. Reciprocal Rank Fusion (RRF): Merge both ranked lists into a single
   ranked list using the formula ``1 / (k + rank)`` with ``k = 60``.

Dense and sparse searches are also available independently via
``dense_search()`` and ``sparse_search()``.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from groq import AsyncGroq
from tavily import AsyncTavilyClient

from src.core.config import Settings
from src.core.logging import get_logger
from src.ingestion.pipeline import Embedder

logger = get_logger(__name__)

# RRF constant — standard value from the original RRF paper.
RRF_K: int = 60

# ── SQL fragments ────────────────────────────────────────────

_DENSE_SQL = text("""
    SELECT c.id AS chunk_id,
           c.document_id,
           c.content,
           c.chunk_index,
           c.page_number,
           d.filename AS document_filename,
           (c.embedding <=> CAST(:query_vec AS vector)) AS distance
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE c.tenant_id = :tenant_id
      AND d.deleted_at IS NULL
    ORDER BY c.embedding <=> CAST(:query_vec AS vector)
    LIMIT :limit
""")

_SPARSE_SQL = text("""
    SELECT c.id AS chunk_id,
           c.document_id,
           c.content,
           c.chunk_index,
           c.page_number,
           d.filename AS document_filename,
           ts_rank_cd(c.tsv, plainto_tsquery('english', :query)) AS rank
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE c.tenant_id = :tenant_id
      AND d.deleted_at IS NULL
      AND c.tsv @@ plainto_tsquery('english', :query)
    ORDER BY rank DESC
    LIMIT :limit
""")


@dataclass
class RankedChunk:
    """A chunk with its fused retrieval score."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    chunk_index: int
    page_number: int | None
    score: float
    document_filename: str

@dataclass
class RankedWebResult:
    """A web search result."""
    url: str
    title: str
    content: str
    score: float


# ── Individual search functions ──────────────────────────────


async def dense_search(
    query: str,
    tenant_id: uuid.UUID,
    embedder: Embedder,
    db: AsyncSession,
    top_k: int = 5,
) -> list[RankedChunk]:
    """Dense-only retrieval using pgvector cosine distance.

    Args:
        query: User's search query.
        tenant_id: Tenant scope.
        embedder: Embedding model.
        db: Async database session.
        top_k: Number of results.

    Returns:
        List of RankedChunk sorted by cosine similarity (best first).
    """
    query_embedding = embedder.encode([query])[0]
    result = await db.execute(
        _DENSE_SQL,
        {
            "query_vec": str(query_embedding),
            "tenant_id": str(tenant_id),
            "limit": top_k,
        },
    )
    rows = result.mappings().all()

    ranked = [
        RankedChunk(
            chunk_id=uuid.UUID(str(row["chunk_id"])),
            document_id=uuid.UUID(str(row["document_id"])),
            content=row["content"],
            chunk_index=row["chunk_index"],
            page_number=row.get("page_number"),
            score=round(1.0 - float(row["distance"]), 6),  # cosine similarity
            document_filename=row["document_filename"],
        )
        for row in rows
    ]

    logger.info(
        "dense_search_complete",
        query_length=len(query),
        results=len(ranked),
    )
    return ranked


async def sparse_search(
    query: str,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    top_k: int = 5,
) -> list[RankedChunk]:
    """Sparse-only retrieval using PostgreSQL tsvector full-text search.

    Args:
        query: User's search query.
        tenant_id: Tenant scope.
        db: Async database session.
        top_k: Number of results.

    Returns:
        List of RankedChunk sorted by ts_rank_cd score (best first).
    """
    result = await db.execute(
        _SPARSE_SQL,
        {
            "query": query,
            "tenant_id": str(tenant_id),
            "limit": top_k,
        },
    )
    rows = result.mappings().all()

    ranked = [
        RankedChunk(
            chunk_id=uuid.UUID(str(row["chunk_id"])),
            document_id=uuid.UUID(str(row["document_id"])),
            content=row["content"],
            chunk_index=row["chunk_index"],
            page_number=row.get("page_number"),
            score=round(float(row["rank"]), 6),
            document_filename=row["document_filename"],
        )
        for row in rows
    ]

    logger.info(
        "sparse_search_complete",
        query_length=len(query),
        results=len(ranked),
    )
    return ranked


# ── Hybrid search (ADR-005: parallel via asyncio.gather) ─────


async def hybrid_search(
    query: str,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    embedder: Embedder,
    db: AsyncSession,
    settings: Settings,
    top_k: int = 5,
    candidate_multiplier: int = 2,
) -> tuple[list[RankedChunk | RankedWebResult], str | None]:
    """Execute a hybrid search combining dense and sparse retrieval.

    Both retrievals run concurrently via ``asyncio.gather`` (ADR-005).
    If no internal results are found, falls back to web search.
    Then synthesizes an answer using Groq.

    Returns:
        A tuple of (ranked_chunks, answer).
    """
    candidates = top_k * candidate_multiplier

    # Embed query (CPU-bound, done once before both searches)
    query_embedding = embedder.encode([query])[0]

    # ADR-005: Run dense + sparse in parallel using independent sessions
    async def _run_dense() -> list[dict]:
        async with AsyncSession(bind=db.bind) as session:
            result = await session.execute(
                _DENSE_SQL,
                {
                    "query_vec": str(query_embedding),
                    "tenant_id": str(tenant_id),
                    "limit": candidates,
                },
            )
            return [dict(r) for r in result.mappings().all()]

    async def _run_sparse() -> list[dict]:
        async with AsyncSession(bind=db.bind) as session:
            result = await session.execute(
                _SPARSE_SQL,
                {
                    "query": query,
                    "tenant_id": str(tenant_id),
                    "limit": candidates,
                },
            )
            return [dict(r) for r in result.mappings().all()]

    # Run concurrently using asyncio.gather
    dense_rows, sparse_rows = await asyncio.gather(_run_dense(), _run_sparse())

    # ── Reciprocal Rank Fusion ───────────────────────────────
    fused: list[RankedChunk | RankedWebResult] = _reciprocal_rank_fusion(dense_rows, sparse_rows, top_k)

    logger.info(
        "hybrid_search_internal_complete",
        query_length=len(query),
        dense_candidates=len(dense_rows),
        sparse_candidates=len(sparse_rows),
        fused_results=len(fused),
    )

    # CRAG Evaluation: If we have internal chunks, evaluate their relevance
    is_useful = False
    if fused:
        is_useful = await _evaluate_chunks(query, fused, settings)
        if not is_useful:
            logger.info("crag_eval_failed_triggering_web_search", query=query)

    # Fallback to web search if no internal results OR if CRAG deemed them useless
    if not fused or not is_useful:
        if not fused:
            logger.info("hybrid_search_fallback_to_web", query=query)
        web_fused = await _fallback_web_search(query, settings, top_k)
        if web_fused:
            fused = web_fused

    # Synthesize answer
    answer = None
    if fused:
        answer = await _synthesize_answer(query, fused, settings)

    return fused, answer


async def _evaluate_chunks(query: str, chunks: list[RankedChunk | RankedWebResult], settings: Settings) -> bool:
    """CRAG evaluation: Determine if retrieved chunks are relevant to the query."""
    if not settings.groq_api_key:
        return True  # default to true if no API key to avoid breaking the flow

    client = AsyncGroq(api_key=settings.groq_api_key)
    context_text = ""
    for idx, chunk in enumerate(chunks, 1):
        if isinstance(chunk, RankedChunk):
            context_text += f"\n[{idx}]: {chunk.content}\n"

    prompt = f"""You are a relevance evaluator for a research platform.
Query: {query}
Context:
{context_text}

Does the context contain any relevant information to help answer the query?
Reply strictly with exactly "YES" or "NO"."""

    try:
        completion = await client.chat.completions.create(
            model=settings.groq_model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
        )
        response = completion.choices[0].message.content.strip().upper()
        # If the model says NO, it's useless. Otherwise, assume useful.
        return "NO" not in response
    except Exception as e:
        logger.error("crag_eval_failed", error=str(e))
        return True  # fallback to assuming it's good if eval fails


def _reciprocal_rank_fusion(
    dense_rows: list[dict],
    sparse_rows: list[dict],
    top_k: int,
) -> list[RankedChunk]:
    """Merge two ranked lists using Reciprocal Rank Fusion.

    RRF score = sum of 1 / (k + rank) across all lists where the
    document appears. k=60 is the standard constant.
    """
    scores: dict[uuid.UUID, float] = {}
    metadata: dict[uuid.UUID, dict] = {}

    # Score dense results
    for rank, row in enumerate(dense_rows, start=1):
        chunk_id = uuid.UUID(str(row["chunk_id"]))
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        metadata[chunk_id] = dict(row)

    # Score sparse results
    for rank, row in enumerate(sparse_rows, start=1):
        chunk_id = uuid.UUID(str(row["chunk_id"]))
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        if chunk_id not in metadata:
            metadata[chunk_id] = dict(row)

    # Sort by fused score descending
    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)

    results: list[RankedChunk] = []
    for chunk_id in sorted_ids[:top_k]:
        meta = metadata[chunk_id]
        results.append(
            RankedChunk(
                chunk_id=chunk_id,
                document_id=uuid.UUID(str(meta["document_id"])),
                content=meta["content"],
                chunk_index=meta["chunk_index"],
                page_number=meta.get("page_number"),
                score=round(scores[chunk_id], 6),
                document_filename=meta["document_filename"],
            )
        )

    return results
async def _synthesize_answer(
    query: str,
    context_chunks: list[RankedChunk | RankedWebResult],
    settings: Settings,
) -> str | None:
    """Generate a concise RAG answer using Groq."""
    if not settings.groq_api_key:
        logger.warning("missing_groq_api_key")
        return None

    client = AsyncGroq(api_key=settings.groq_api_key)
    
    # Check if context is from internal or web
    is_web = any(isinstance(c, RankedWebResult) for c in context_chunks)
    source_type_str = "web search results" if is_web else "internal workspace documents"

    # Build context string
    context_text = ""
    for idx, chunk in enumerate(context_chunks, 1):
        if isinstance(chunk, RankedChunk):
            context_text += f"\n[Source {idx} - {chunk.document_filename}]:\n{chunk.content}\n"
        else:
            context_text += f"\n[Source {idx} - Web: {chunk.title}]:\n{chunk.content}\n"

    system_prompt = f"""You are a helpful AI research assistant.
Answer the user's query using ONLY the provided context, which comes from {source_type_str}.
If the context does not contain enough information to fully answer the query, clearly state that you don't have enough information based on the sources, and answer as much as you can.
DO NOT hallucinate or invent facts outside the context.
Keep your answer concise and useful."""

    user_prompt = f"Context:\n{context_text}\n\nUser Query: {query}"

    try:
        completion = await client.chat.completions.create(
            model=settings.groq_model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=1024,
        )
        return completion.choices[0].message.content
    except Exception as e:
        logger.error("groq_synthesis_failed", error=str(e))
        return None


async def _fallback_web_search(
    query: str,
    settings: Settings,
    top_k: int,
) -> list[RankedWebResult]:
    """Fallback to Tavily web search when no internal documents match."""
    if not settings.tavily_api_key:
        logger.warning("missing_tavily_api_key_for_fallback")
        return []

    client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    try:
        response = await client.search(query=query, max_results=top_k)
        results = response.get("results", [])
        web_chunks = []
        for idx, res in enumerate(results):
            web_chunks.append(
                RankedWebResult(
                    url=res.get("url", ""),
                    title=res.get("title", ""),
                    content=res.get("content", ""),
                    score=float(res.get("score", 1.0 - (idx * 0.1))),
                )
            )
        return web_chunks
    except Exception as e:
        logger.error("tavily_fallback_failed", error=str(e))
        return []

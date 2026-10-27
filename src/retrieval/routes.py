"""Search API routes.

Endpoints:
    POST /search           — Hybrid (dense + sparse + RRF)
    POST /search/semantic  — Dense-only (pgvector cosine)
    POST /search/keyword   — Sparse-only (tsvector ts_rank_cd)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user, get_db_session
from src.auth.models import User
from src.core.config import get_settings
from src.ingestion.pipeline import Embedder, SentenceTransformerEmbedder
from src.retrieval import service as search_service
from src.retrieval.schemas import ChunkResult, WebResult, SearchRequest, SearchResponse
from src.tenants.dependencies import get_current_tenant
from src.tenants.schemas import TenantContext

router = APIRouter(prefix="/search", tags=["search"])


def _get_embedder(request: Request) -> Embedder:
    """Lazy-initialize and cache the embedding model on app state."""
    if not hasattr(request.app.state, "embedder"):
        settings = get_settings()
        request.app.state.embedder = SentenceTransformerEmbedder(
            model_name=settings.embedding_model_name,
            dim=settings.embedding_dimension,
        )
    return request.app.state.embedder


def _ranked_to_result(r: search_service.RankedChunk | search_service.RankedWebResult) -> ChunkResult | WebResult:
    """Convert a RankedChunk or RankedWebResult dataclass to a schema."""
    if isinstance(r, search_service.RankedWebResult):
        return WebResult(
            url=r.url,
            title=r.title,
            content=r.content,
            score=r.score,
        )
    return ChunkResult(
        chunk_id=r.chunk_id,
        document_id=r.document_id,
        content=r.content,
        chunk_index=r.chunk_index,
        page_number=r.page_number,
        score=r.score,
        document_filename=r.document_filename,
    )


@router.post("", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
    embedder: Embedder = Depends(_get_embedder),
) -> SearchResponse:
    """Hybrid search across the user's documents.

    Combines dense (pgvector) and sparse (tsvector) retrieval
    using Reciprocal Rank Fusion.
    """
    settings = get_settings()
    results, answer = await search_service.hybrid_search(
        query=body.query,
        user_id=user.id,
        tenant_id=tenant.org_id,
        embedder=embedder,
        db=db,
        settings=settings,
        top_k=body.top_k,
        candidate_multiplier=settings.retrieval_candidate_multiplier,
    )

    return SearchResponse(
        query=body.query,
        results=[_ranked_to_result(r) for r in results],
        total=len(results),
        answer=answer,
    )


@router.post("/semantic", response_model=SearchResponse)
async def semantic_search(
    body: SearchRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
    embedder: Embedder = Depends(_get_embedder),
) -> SearchResponse:
    """Dense-only search using pgvector cosine similarity."""
    results = await search_service.dense_search(
        query=body.query,
        tenant_id=tenant.org_id,
        embedder=embedder,
        db=db,
        top_k=body.top_k,
    )
    return SearchResponse(
        query=body.query,
        results=[_ranked_to_result(r) for r in results],
        total=len(results),
    )


@router.post("/keyword", response_model=SearchResponse)
async def keyword_search(
    body: SearchRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> SearchResponse:
    """Sparse-only search using PostgreSQL tsvector full-text search."""
    results = await search_service.sparse_search(
        query=body.query,
        tenant_id=tenant.org_id,
        db=db,
        top_k=body.top_k,
    )
    return SearchResponse(
        query=body.query,
        results=[_ranked_to_result(r) for r in results],
        total=len(results),
    )

"""Evaluation API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user, get_db_session
from src.auth.models import User
from src.core.config import get_settings
from src.evaluation import service as eval_service
from src.evaluation.llm_gateway import LLMGateway
from src.evaluation.schemas import RelevanceRequest, RelevanceResponse
from src.tenants.dependencies import get_current_tenant
from src.tenants.schemas import TenantContext

router = APIRouter(prefix="/evaluate", tags=["evaluation"])


def _get_llm_gateway(request: Request) -> LLMGateway:
    """Lazy-initialize and cache the LLM gateway on app state."""
    if not hasattr(request.app.state, "llm_gateway"):
        settings = get_settings()
        request.app.state.llm_gateway = LLMGateway(settings)
    return request.app.state.llm_gateway


@router.post("/relevance", response_model=RelevanceResponse)
async def evaluate_relevance(
    body: RelevanceRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
    gateway: LLMGateway = Depends(_get_llm_gateway),
) -> RelevanceResponse:
    """Evaluate the relevance of retrieved chunks against a query.

    Uses CRAG-style LLM grading: relevant / ambiguous / not_relevant.
    Rate-limited and circuit-broken via the LLM gateway.
    """
    settings = get_settings()
    evaluations = await eval_service.evaluate_relevance(
        query=body.query,
        chunk_ids=body.chunk_ids,
        user_id=user.id,
        tenant_id=tenant.org_id,
        db=db,
        gateway=gateway,
    )
    return RelevanceResponse(
        query=body.query,
        evaluations=evaluations,
        model=settings.llm_model_name,
        circuit_state=gateway.circuit_state,
    )

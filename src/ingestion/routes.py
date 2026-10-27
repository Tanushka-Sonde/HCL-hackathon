"""Ingestion job status routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user, get_db_session
from src.auth.models import User
from src.core.exceptions import NotFoundError
from src.ingestion import service as job_service
from src.ingestion.job_schemas import JobListResponse
from src.ingestion.schemas import JobResponse
from src.tenants.dependencies import get_current_tenant
from src.tenants.schemas import TenantContext

router = APIRouter(prefix="/jobs", tags=["ingestion"])


@router.get("", response_model=JobListResponse)
async def list_jobs(
    cursor: str | None = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> JobListResponse:
    """List all ingestion jobs with cursor pagination."""
    jobs, next_cursor = await job_service.list_jobs(
        user.id,
        tenant.org_id,
        db,
        cursor=cursor,
        limit=min(limit, 100),
    )
    return JobListResponse(
        items=[JobResponse.model_validate(j) for j in jobs],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> JobResponse:
    """Get the status of an ingestion job."""
    job = await job_service.get_job(job_id, user.id, tenant.org_id, db)
    if job is None:
        raise NotFoundError("IngestionJob", str(job_id))
    return JobResponse.model_validate(job)


@router.get("/document/{document_id}", response_model=list[JobResponse])
async def list_jobs_for_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> list[JobResponse]:
    """List all ingestion jobs for a document."""
    jobs = await job_service.list_jobs_for_document(
        document_id, user.id, tenant.org_id, db
    )
    return [JobResponse.model_validate(j) for j in jobs]

"""Background ingestion worker daemon.

Polls the ``ingestion_jobs`` table using SELECT ... FOR UPDATE SKIP LOCKED,
processes documents through the ingestion pipeline, and stores chunks.

Run as a standalone process::

    python -m src.ingestion.worker
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket

from src.core.config import Settings, get_settings
from src.core.database import Database
from src.core.logging import configure_logging, get_logger
from src.documents.storage import ObjectStorage
from src.ingestion import service as job_service
from src.ingestion.pipeline import (
    IngestionPipeline,
    RecursiveTextChunker,
    SemanticTextChunker,
    SentenceTransformerEmbedder,
)
from src.tenants.middleware import set_tenant_context, set_worker_context

# Import ORM models so SQLAlchemy registers all relationships
# before mapper configuration occurs in the standalone worker.
from src.auth.models import User
from src.documents.models import Document
from src.ingestion.models import Chunk, IngestionJob
from src.tenants.models import Organization

logger = get_logger(__name__)


async def process_single_job(
    job_id: object,
    document_id: object,
    user_id: object,
    tenant_id: object,
    version: int,
    attempt_count: int,
    max_attempts: int,
    db: Database,
    storage: ObjectStorage,
    pipeline: IngestionPipeline,
) -> None:
    """Process a single claimed job.

    Runs in its own transaction, separate from the claim transaction.
    On failure, marks the job as failed (or dead) in a third transaction.
    """
    import uuid as _uuid

    _job_id = _uuid.UUID(str(job_id))
    _doc_id = _uuid.UUID(str(document_id))
    _user_id = _uuid.UUID(str(user_id))
    _tenant_id = _uuid.UUID(str(tenant_id))

    try:
        async with db.session_factory() as session:
            await set_worker_context(session)
            await set_tenant_context(session, _tenant_id)
            # Transition to 'running'
            ok = await job_service.mark_running(_job_id, version, session)
            if not ok:
                logger.warning("optimistic_lock_failed", job_id=str(_job_id))
                await session.rollback()
                return

            # Load document metadata
            doc = await session.get(Document, _doc_id)
            if doc is None or doc.storage_key is None:
                raise ValueError(f"Document {_doc_id} not found or has no storage key.")

            # Download from MinIO
            file_data = await storage.download(doc.storage_key)

            # Run pipeline: extract → chunk → embed
            chunks = pipeline.process(file_data, doc.mime_type)

            # Store chunks + update statuses
            await job_service.complete_job(
                _job_id, _doc_id, chunks, _user_id, _tenant_id, session
            )
            await session.commit()

    except Exception as exc:
        logger.exception(
            "job_processing_failed",
            job_id=str(_job_id),
            error=str(exc),
        )
        # Mark as failed in a separate transaction
        try:
            async with db.session_factory() as session:
                await set_worker_context(session)
                await set_tenant_context(session, _tenant_id)
                await job_service.fail_job(
                    _job_id,
                    _doc_id,
                    str(exc),
                    attempt_count,
                    max_attempts,
                    session,
                )
                await session.commit()
        except Exception as fail_exc:
            logger.exception(
                "fail_job_update_failed",
                job_id=str(_job_id),
                error=str(fail_exc),
            )


async def run_worker(settings: Settings | None = None) -> None:
    """Main worker loop.

    Polls the job queue at a configurable interval. Handles
    graceful shutdown via SIGINT/SIGTERM.
    """
    if settings is None:
        settings = get_settings()

    configure_logging(settings.log_level, settings.is_production)

    db = Database(settings)
    storage = ObjectStorage(settings)
    await storage.ensure_bucket()

    embedder = SentenceTransformerEmbedder(
        model_name=settings.embedding_model_name,
        dim=settings.embedding_dimension,
    )
    if settings.chunking_strategy == "semantic":
        chunker: RecursiveTextChunker | SemanticTextChunker = SemanticTextChunker(
            embedder=embedder,
            threshold_percentile=settings.chunking_semantic_threshold_percentile,
            max_chunk_size=2048,
            buffer_size=settings.chunking_semantic_buffer_size,
        )
    else:
        chunker = RecursiveTextChunker(chunk_size=2048, chunk_overlap=256)
    pipeline = IngestionPipeline(embedder, chunker)

    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    shutdown_event = asyncio.Event()

    def _handle_signal(sig: int, frame: object) -> None:
        logger.info("shutdown_requested", worker_id=worker_id, signal=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(
        "worker_started",
        worker_id=worker_id,
        poll_interval=settings.worker_poll_interval_seconds,
        max_concurrent=settings.worker_max_concurrent_jobs,
    )

    try:
        while not shutdown_event.is_set():
            # Claim phase (separate transaction)
            job = None
            async with db.session_factory() as session:
                await set_worker_context(session)
                job = await job_service.claim_next_job(session, worker_id)
                await session.commit()

            if job is None:
                # No work available — sleep
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=settings.worker_poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
                continue

            # Process phase (separate transaction per job)
            await process_single_job(
                job_id=job.id,
                document_id=job.document_id,
                user_id=job.user_id,
                tenant_id=job.tenant_id,
                version=job.version,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                db=db,
                storage=storage,
                pipeline=pipeline,
            )

    finally:
        await db.dispose()
        logger.info("worker_stopped", worker_id=worker_id)


def main() -> None:
    """Entry point for ``python -m src.ingestion.worker``."""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

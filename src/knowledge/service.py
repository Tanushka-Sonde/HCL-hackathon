"""Knowledge service orchestrator (workflow steps 1-11 of the brief).

ingest:  validate -> extract (page/section/metadata) -> chunk -> embed -> index
query:   context -> safety precheck -> route -> retrieve/rerank -> tool ->
         conflict check -> generate -> validate -> outcome -> event store
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.core.exceptions import AuthorizationError, ValidationError
from src.core.logging import get_logger
from src.ingestion.pipeline import RecursiveTextChunker
from src.knowledge.anomaly import detect_anomalies
from src.knowledge.auth import SYSTEM_EVAL_USER, AuthService, CurrentUser
from src.knowledge.calc import apply_calcs
from src.knowledge.context import (
    ConversationMemory,
    Turn,
    resolve,
    rewrite_with_llm,
)
from src.knowledge.embeddings import build_embedder, build_reranker
from src.knowledge.generation import (
    INSUFFICIENT_ANSWER,
    SYSTEM_PROMPT,
    build_user_prompt,
    fit_to_budget,
    generate,
)
from src.knowledge.masking import detect_pii, mask_for_user, mask_rows, merge_counts
from src.knowledge.outcome import confidence_for, decide_outcome
from src.knowledge.parsing import (
    ALLOWED_EXTENSIONS,
    Asset,
    TextUnit,
    file_too_large_message,
    parse_document,
    split_table,
)
from src.knowledge.retrieval import Candidate, KnowledgeIndex
from src.knowledge.router import route_query, strip_data_terms
from src.knowledge.safety import (
    BLOCKED_QUERY_ANSWER,
    detect_injection,
    sanitize_evidence,
)
from src.knowledge.schemas import (
    DemoIngestResponse,
    DocumentInfo,
    Evidence,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    ToolCall,
)
from src.knowledge.store import KnowledgeStore
from src.knowledge.tools import TEMPLATES, SQLTool
from src.knowledge.validation import (
    assess_grounding,
    detect_conflicts,
    is_insufficient,
    validate_citations,
)
from src.knowledge.vision import VisionClient, load_prompt
from src.knowledge.visuals import build_visuals, extract_chart_block

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _sanitize_error(exc: BaseException) -> str:
    """Exception category + truncated message, without paths or secrets."""
    msg = str(exc).replace(str(PROJECT_ROOT), "<app>")
    return f"{type(exc).__name__}: {msg[:200]}"


@dataclass
class ImageInput:
    """An image attached to a question, already described by the vision model."""

    description: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    size_bytes: int = 0
    stored_path: str | None = None


class KnowledgeService:
    """Owns the store, index, models, tool and conversation memory."""

    def __init__(
        self,
        settings: Settings,
        data_dir: Path | None = None,
        demo_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.data_dir = Path(data_dir or PROJECT_ROOT / settings.kis_data_dir)
        self.demo_dir = Path(demo_dir or PROJECT_ROOT / "demo")
        self.store = KnowledgeStore(self.data_dir / "kis.db")
        self.auth = AuthService(self.store, settings)
        self.vision = VisionClient(settings)
        self.embedder, self.embedder_name, semantic = build_embedder(settings)
        self.reranker = build_reranker(settings)
        self.index = KnowledgeIndex(self.embedder, semantic)
        self.index.rebuild(self.store.load_chunks())
        self.tool = SQLTool(
            self.data_dir / "business.db", self.demo_dir / "business_seed.sql"
        )
        self.memory = ConversationMemory(settings.kis_context_turns)
        self.chunker = RecursiveTextChunker(
            chunk_size=settings.kis_chunk_size, chunk_overlap=settings.kis_chunk_overlap
        )
        self._ingest_lock = threading.Lock()

    # ── Configuration ────────────────────────────────────────

    def config_label(self, config_id: str) -> str:
        pipeline = {
            "A": "vector-only",
            "C": "hybrid(vector+bm25,rrf)-no-rerank",
        }.get(config_id, f"hybrid(vector+bm25,rrf)+rerank:{self.reranker.name}")
        return (
            f"{config_id}|{pipeline}|emb:{self.embedder_name}|"
            f"chunk:{self.settings.kis_chunk_size}/{self.settings.kis_chunk_overlap}"
        )

    def describe(self) -> dict[str, Any]:
        return {
            "mode": "local-demo",
            "app_version": self.settings.app_version,
            "embedder": self.embedder_name,
            "reranker": self.reranker.name,
            "llm_provider": "groq"
            if self.settings.groq_api_key
            else "extractive (no GROQ_API_KEY)",
            "llm_model": self.settings.groq_model_name
            if self.settings.groq_api_key
            else "extractive-v1",
            "prompt_template_version": self.settings.prompt_template_version,
            "chunk_size": self.settings.kis_chunk_size,
            "chunk_overlap": self.settings.kis_chunk_overlap,
            "min_evidence_score": self.settings.kis_min_evidence_score,
            "grounding_threshold": self.settings.kis_grounding_threshold,
            "indexed_chunks": len(self.index),
            "configs": {c: self.config_label(c) for c in ("A", "B", "C")},
            "vision_model": self.vision.model if self.vision.enabled else None,
            "vision_enabled": self.vision.enabled,
            "max_upload_mb": self.settings.kis_max_upload_mb,
            "allowed_types": sorted(ALLOWED_EXTENSIONS),
            "sql_templates": sorted(TEMPLATES),
        }

    # ── Ingestion ────────────────────────────────────────────

    def ingest(
        self,
        filename: str,
        content: bytes,
        metadata: dict[str, str | None] | None = None,
        uploaded_by: str | None = None,
    ) -> IngestResponse:
        content_hash = hashlib.sha256(content).hexdigest()
        # Check for a duplicate first, so re-uploads never spend vision calls.
        existing = self.store.find_document_by_hash(content_hash)
        if existing:
            return IngestResponse(
                document=DocumentInfo(**_doc_fields(existing)), duplicate=True
            )
        parsed = parse_document(
            filename,
            content,
            self.settings.kis_max_upload_mb * 1_048_576,
            overrides=metadata,
            vision=self.vision,
            vision_max_calls=self.settings.kis_vision_max_pages,
        )
        with self._ingest_lock:
            existing = self.store.find_document_by_hash(content_hash)
            if existing:
                return IngestResponse(
                    document=DocumentInfo(**_doc_fields(existing)), duplicate=True
                )

            meta = parsed.metadata
            doc_uuid = str(uuid.uuid4())
            doc = {
                "id": doc_uuid,
                "filename": parsed.filename,
                "doc_id": meta.get("doc-id", ""),
                "title": meta.get("title", parsed.filename),
                "category": meta.get("category"),
                "version": meta.get("version"),
                "status": meta.get("status"),
                "effective_date": meta.get("effective"),
                "mime_type": parsed.mime_type,
                "size_bytes": parsed.size_bytes,
                "pages": parsed.pages,
                "content_hash": content_hash,
                "created_at": _now(),
                "uploaded_by": uploaded_by,
                "vision_input_tokens": parsed.vision_input_tokens,
                "vision_output_tokens": parsed.vision_output_tokens,
            }
            header = (
                f"{doc['title']} ({doc['doc_id']}) version {doc['version'] or 'n/a'} "
                f"{doc['status'] or ''}".strip()
            )
            chunks: list[dict[str, Any]] = []
            for unit in parsed.units:
                for piece in self._unit_pieces(unit):
                    section = f" | {unit.section}" if unit.section else ""
                    chunks.append(
                        {
                            "id": str(uuid.uuid4()),
                            "document_id": doc_uuid,
                            "chunk_index": len(chunks),
                            "page": unit.page,
                            "section": unit.section,
                            "content": piece,
                            "index_text": f"{header}{section}\n{piece}",
                            "content_type": unit.content_type,
                            "source_method": unit.source_method,
                            "asset_id": unit.asset_id,
                            "bbox": unit.bbox,
                        }
                    )
            embeddings = self.embedder.encode([c["index_text"] for c in chunks])
            for chunk, emb in zip(chunks, embeddings, strict=False):
                chunk["embedding"] = [round(float(x), 6) for x in emb]
            doc["chunk_count"] = len(chunks)
            assets = self._save_assets(doc_uuid, parsed.assets)
            try:
                self.store.insert_document(doc, chunks, assets)
            except Exception:
                self._remove_asset_files(doc_uuid)
                raise
            self.index.rebuild(self.store.load_chunks())
        logger.info(
            "kis_document_ingested",
            filename=filename,
            chunks=len(chunks),
            assets=len(assets),
            vision_calls=parsed.vision_calls,
        )
        return IngestResponse(
            document=DocumentInfo(**_doc_fields(doc)),
            skipped_pages=parsed.skipped_pages,
            warnings=parsed.warnings,
        )

    async def describe_query_image(
        self, image_bytes: bytes, filename: str, question: str
    ) -> ImageInput:
        """Validate an attached image and describe it with the vision model."""
        limit = self.settings.kis_query_image_max_mb * 1_048_576
        if len(image_bytes) > limit:
            raise ValidationError(file_too_large_message(len(image_bytes), limit))
        ext = Path(filename).suffix.lower()
        signatures = {
            ".png": (b"\x89PNG\r\n\x1a\n",),
            ".jpg": (b"\xff\xd8\xff",),
            ".jpeg": (b"\xff\xd8\xff",),
            ".webp": (b"RIFF",),
        }
        if ext not in signatures:
            raise ValidationError("Attach a .png, .jpg or .webp image.")
        if not image_bytes.startswith(signatures[ext]):
            raise ValidationError(
                f"File has a {ext} extension but is not a valid image."
            )
        if not self.vision.enabled:
            raise ValidationError(
                f"Image questions need vision, and {VisionClient.UNAVAILABLE}."
            )
        prompt = load_prompt("query_image_v1").replace("{question}", question[:500])
        result = await self.vision.adescribe(image_bytes, prompt)
        if not result.ok or not result.text.strip():
            raise ValidationError(
                f"Could not read the image: {result.error or 'no description'}"
            )
        stored = None
        if self.settings.kis_store_query_images:
            folder = self.data_dir / "query_images"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{uuid.uuid4()}{ext}"
            path.write_bytes(image_bytes)
            stored = path.relative_to(self.data_dir).as_posix()
        return ImageInput(
            description=result.text.strip(),
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            size_bytes=len(image_bytes),
            stored_path=stored,
        )

    def _unit_pieces(self, unit: TextUnit) -> list[str]:
        """Text is chunked; a table is one chunk (split by rows, header kept)."""
        if unit.content_type == "table":
            where = f" (page {unit.page})" if unit.page else ""
            caption = f"Table: {unit.section or 'untitled table'}{where}"
            return [
                f"{caption}\n{piece}"
                for piece in split_table(
                    unit.text, self.settings.kis_table_chunk_max_chars
                )
            ]
        if unit.content_type in ("chart", "image"):
            return [unit.text]  # already a compact, self-describing summary
        return self.chunker.chunk(unit.text)

    # ── Assets (page renders, charts, uploaded images) ───────

    def _asset_dir(self, document_id: str) -> Path:
        return self.data_dir / "assets" / document_id

    def _save_assets(self, document_id: str, assets: list[Asset]) -> list[dict]:
        rows = []
        if not assets:
            return rows
        folder = self._asset_dir(document_id)
        folder.mkdir(parents=True, exist_ok=True)
        for asset in assets:
            path = folder / f"{asset.asset_id}.png"
            path.write_bytes(asset.png)
            rows.append(
                {
                    "id": asset.asset_id,
                    "document_id": document_id,
                    "page": asset.page,
                    "kind": asset.kind,
                    "path": path.relative_to(self.data_dir).as_posix(),
                    "width": asset.width,
                    "height": asset.height,
                }
            )
        return rows

    def _remove_asset_files(self, document_id: str) -> None:
        shutil.rmtree(self._asset_dir(document_id), ignore_errors=True)

    def asset_path(self, asset_id: str) -> Path | None:
        row = self.store.get_asset(asset_id)
        if row is None:
            return None
        path = (self.data_dir / row["path"]).resolve()
        # Never serve anything outside the data directory.
        if not path.is_relative_to(self.data_dir.resolve()) or not path.is_file():
            return None
        return path

    def ingest_demo(self) -> DemoIngestResponse:
        corpus = self.demo_dir / "corpus"
        ingested: list[IngestResponse] = []
        errors: list[dict[str, str]] = []
        for path in sorted(corpus.glob("*")):
            if path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            try:
                ingested.append(self.ingest(path.name, path.read_bytes()))
            except Exception as exc:
                errors.append({"filename": path.name, "error": _sanitize_error(exc)})
        return DemoIngestResponse(ingested=ingested, errors=errors)

    def list_documents(self) -> list[DocumentInfo]:
        return [DocumentInfo(**_doc_fields(d)) for d in self.store.list_documents()]

    def delete_document(self, document_id: str) -> bool:
        with self._ingest_lock:
            deleted = self.store.delete_document(document_id)
            if deleted:
                self._remove_asset_files(document_id)
            if deleted:
                self.index.rebuild(self.store.load_chunks())
        return deleted

    # ── Query ────────────────────────────────────────────────

    async def query(
        self,
        req: QueryRequest,
        correlation_id: str | None = None,
        eval_meta: dict[str, Any] | None = None,
        user: CurrentUser | None = None,
        image: ImageInput | None = None,
    ) -> QueryResponse:
        settings = self.settings
        t_start = time.perf_counter()
        query_id = str(uuid.uuid4())
        session_id = req.session_id or str(uuid.uuid4())
        # Evaluation runs (started by an admin) act as the system eval user.
        user = user or CurrentUser(**SYSTEM_EVAL_USER)
        # A conversation belongs to the user who started it.
        owner = self.store.session_owner(session_id)
        if owner is not None and owner != user.id:
            raise AuthorizationError("This conversation belongs to another user.")
        self.store.touch_session(session_id, user.id, _now())
        memory_key = f"{user.id}:{session_id}"
        correlation_id = correlation_id or query_id
        min_rel = settings.kis_min_evidence_score

        stages: dict[str, str] = {}
        stage_errors: dict[str, str] = {}
        errors: list[dict[str, Any]] = []
        perf: dict[str, float] = {
            "vision_ms": image.latency_ms if image else 0.0,
            "context_ms": 0.0,
            "retrieval_ms": 0.0,
            "tool_ms": 0.0,
            "llm_ms": 0.0,
            "validation_ms": 0.0,
        }

        def record_error(stage: str, exc: BaseException) -> None:
            stage_errors[stage] = _sanitize_error(exc)
            errors.append(
                {
                    "stage": stage,
                    "category": type(exc).__name__,
                    "message": _sanitize_error(exc),
                    "correlation_id": correlation_id,
                }
            )
            logger.exception("kis_stage_failed", stage=stage, query_id=query_id)

        # Safety precheck on the user's own text
        query_injection = detect_injection(req.query)
        injection_blocked = bool(query_injection)

        # Step 4 — query understanding & conversation context
        t = time.perf_counter()
        history = self.memory.history(memory_key)
        resolution = resolve(req.query, history)
        normalized, selected_turns = resolution.normalized, resolution.selected_turns
        rewrite_tokens = (0, 0)
        if (
            resolution.method == "rule"
            and settings.groq_api_key
            and not injection_blocked
        ):
            text, t_in, t_out = await rewrite_with_llm(
                req.query, selected_turns[-1], settings
            )
            rewrite_tokens = (t_in, t_out)
            if text:
                normalized, resolution.method = text, "llm"
        # An attached image: its sanitized description joins the question for
        # routing and retrieval, and is citable as [U1].
        image_text: str | None = None
        image_injections: list[str] = []
        if image is not None:
            clean = sanitize_evidence(image.description)
            image_text = clean.text[:1500]
            image_injections = clean.removed
            normalized = f"{normalized}\n[Image content]: {image_text}"
        perf["context_ms"] = _ms(t)
        stages["context"] = "ok"

        # Step 5 — routing on the user's own words. A follow-up with no
        # signals of its own ("and the international one?") uses the rewrite.
        router_notes: list[str] = []
        decision = route_query(req.query + (f"\n{image_text}" if image_text else ""))
        if selected_turns and not (decision.data_signals or decision.doc_signals):
            decision = route_query(normalized)
            router_notes.append("follow-up without own signals; routed on rewrite")
        stages["routing"] = "ok"

        candidates: list[Candidate] = []
        evidence: list[Evidence] = []
        evidence_found = False
        top_relevance = 0.0
        chunk_injections: list[dict[str, Any]] = []
        tool_calls: list[ToolCall] = []

        async def run_retrieval(text: str) -> None:
            nonlocal candidates, evidence, evidence_found, top_relevance
            t_r = time.perf_counter()
            try:
                # Off the event loop: the cross-encoder is CPU-bound and would
                # otherwise stall every other request (e.g. during an eval run).
                result = await asyncio.to_thread(
                    self.index.search,
                    text,
                    config_id=req.config_id,
                    reranker=self.reranker,
                    top_k=req.top_k,
                    min_relevance=min_rel,
                    category=req.category,
                    status=req.status,
                    doc_id=req.doc_id,
                    version=req.version,
                )
                candidates = result.candidates
                evidence_found = result.evidence_found
                top_relevance = result.top_relevance
                evidence = self._to_evidence(result.selected, chunk_injections)
                stages["retrieval"] = "ok" if len(self.index) else "empty_index"
            except Exception as exc:
                record_error("retrieval", exc)
                stages["retrieval"] = "error"
            perf["retrieval_ms"] += _ms(t_r)

        if injection_blocked:
            stages.update(retrieval="skipped", tool="skipped", generation="skipped")
        else:
            # Step 6 — retrieval
            if decision.needs_docs:
                docs_query = (
                    strip_data_terms(normalized)
                    if decision.route == "both"
                    else normalized
                )
                await run_retrieval(docs_query)
            else:
                stages["retrieval"] = "not_required"

            # Step 7 — tool execution
            if decision.needs_tool:
                t_t = time.perf_counter()
                try:
                    call = await asyncio.to_thread(
                        self.tool.run, normalized, source_id="T1"
                    )
                except Exception as exc:
                    call = ToolCall(
                        source_id="T1",
                        name="business_sql",
                        template="unknown",
                        status="error",
                        error="The business data source could not be queried.",
                        error_detail=_sanitize_error(exc),
                        result_summary="tool raised an exception",
                    )
                tool_calls.append(call)
                perf["tool_ms"] = _ms(t_t)
                stages["tool"] = call.status
                # No template fits the question: try the documents instead.
                # A tool *error* is not masked by document text; it stays a
                # controlled, logged failure.
                if call.status == "skipped" and decision.route == "sql_tool":
                    router_notes.append(
                        "no SQL template matched; fell back to document retrieval"
                    )
                    await run_retrieval(normalized)
            else:
                stages["tool"] = "not_required"

        tool_ok = any(tc.status == "success" and tc.row_count > 0 for tc in tool_calls)
        conflicts = detect_conflicts(evidence, min_rel)

        # Step 8 — grounded generation
        llm_status = "ok"
        generation: dict[str, Any] = {
            "provider": None,
            "model": None,
            "prompt_template_version": settings.prompt_template_version,
            "status": "skipped",
            "error": None,
        }
        # Token usage per stage; totals and cost are computed once at the end.
        usage: dict[str, Any] = {
            "cached_tokens": None,
            "by_stage": {
                "context_rewrite": {
                    "input_tokens": rewrite_tokens[0],
                    "output_tokens": rewrite_tokens[1],
                },
                "vision_query": {
                    "input_tokens": image.input_tokens if image else 0,
                    "output_tokens": image.output_tokens if image else 0,
                },
            },
        }
        calculations: list[dict[str, Any]] = []
        model_chart: dict[str, Any] | None = None
        # Token budgets: the request's limits, never above the server caps.
        max_in = min(req.max_input_tokens, settings.kis_max_input_tokens_cap)
        max_out = min(req.max_output_tokens, settings.kis_max_output_tokens_cap)
        budget_info: dict[str, Any] = {
            "estimated_input_tokens": 0,
            "evidence_dropped_for_budget": {"count": 0, "source_ids": []},
            "truncated_source": None,
        }
        output_truncated = False
        if injection_blocked:
            answer = BLOCKED_QUERY_ANSWER
        elif stage_errors:
            answer = "A system error occurred while processing this question. The failure has been logged."
            stages["generation"] = "skipped"
        elif not evidence_found and any(tc.status == "error" for tc in tool_calls):
            answer = (
                "The business data tool failed while answering this question, so no "
                "figures can be given. The failure has been logged for follow-up."
            )
            stages["generation"] = "skipped"
        elif not evidence_found and not tool_ok and not image_text:
            answer = INSUFFICIENT_ANSWER
            stages["generation"] = "skipped"
        else:
            relevant = [ev for ev in evidence if ev.relevance >= min_rel]
            fit = fit_to_budget(
                normalized, relevant, tool_calls, selected_turns, max_in
            )
            budget_info.update(
                estimated_input_tokens=fit.estimated_input_tokens,
                evidence_dropped_for_budget={
                    "count": len(fit.dropped),
                    "source_ids": fit.dropped,
                },
                truncated_source=fit.truncated,
            )
            # Stored for the trace so reviewers see exactly what the model got.
            generation["prompt"] = {
                "system": SYSTEM_PROMPT,
                "user": build_user_prompt(
                    normalized, fit.evidence, tool_calls, selected_turns, image_text
                ),
            }
            t_g = time.perf_counter()
            try:
                gen = await generate(
                    normalized,
                    fit.evidence,
                    tool_calls,
                    selected_turns,
                    conflicts,
                    settings,
                    max_output_tokens=max_out,
                    user_image=image_text,
                )
                output_truncated = gen.finish_reason == "length"
                answer, calculations = apply_calcs(gen.text or INSUFFICIENT_ANSWER)
                answer, model_chart = extract_chart_block(answer)
                if not answer.strip() and model_chart:
                    # The model sent only a chart; describe it with its sources
                    # so the answer still carries citations.
                    tags = " ".join(
                        f"[{s}]" for s in model_chart.get("source_ids") or []
                    )
                    title = str(model_chart.get("title") or "Chart")
                    answer = f"{title} {tags}.".strip() if tags else INSUFFICIENT_ANSWER
                llm_status = gen.status
                generation.update(
                    provider=gen.mode,
                    model=gen.model,
                    status=gen.status,
                    error=gen.error,
                )
                usage["cached_tokens"] = gen.cached_tokens
                usage["by_stage"]["generation"] = {
                    "input_tokens": gen.input_tokens,
                    "output_tokens": gen.output_tokens,
                }
                stages["generation"] = gen.status
                perf["llm_ms"] = gen.latency_ms or _ms(t_g)
            except Exception as exc:
                record_error("generation", exc)
                stages["generation"] = "error"
                answer = "A system error occurred while generating the answer. The failure has been logged."

        # Step 9 — validation
        t_v = time.perf_counter()
        # Citations and grounding are checked on the raw answer; role-based
        # masking is applied afterwards, only to what the user is shown.
        citations = validate_citations(answer, evidence, tool_calls, image_text)
        if stages.get("generation") in ("ok", "fallback"):
            grounding = assess_grounding(
                answer,
                evidence,
                tool_calls,
                calculations,
                question=req.query,
                user_image=image_text,
            )
        else:
            # Blocked / fallback / error messages make no factual claims.
            grounding = {
                "score": None,
                "claims": 0,
                "supported": [],
                "unsupported": [],
                "rule": "not applicable: no generated answer",
            }
        insufficient = is_insufficient(answer)
        visuals, chart_rejection = (
            build_visuals(
                question=req.query,
                model_spec=model_chart,
                evidence=evidence,
                tools=tool_calls,
                citations=citations,
                calculations=calculations,
            )
            if stages.get("generation") in ("ok", "fallback") and not insufficient
            else ([], None)
        )
        if chart_rejection:
            logger.info("kis_chart_rejected", query_id=query_id, **chart_rejection)
        pii_detected = {
            "question": detect_pii(req.query),
            "evidence": merge_counts(*(detect_pii(ev.content) for ev in evidence)),
            "answer": detect_pii(answer),
        }
        view = self._present(answer, evidence, tool_calls, conflicts, user, visuals)
        perf["validation_ms"] = _ms(t_v)
        stages["validation"] = "ok"

        outcome, reasons = decide_outcome(
            stage_errors=stage_errors,
            injection_blocked=injection_blocked,
            needs_tool=decision.needs_tool,
            evidence_found=evidence_found or bool(image_text),
            tool_calls=tool_calls,
            llm_status=llm_status,
            answer_insufficient=insufficient and not injection_blocked,
            citations=citations,
            grounding_score=grounding["score"],
            grounding_threshold=settings.kis_grounding_threshold,
            output_truncated=output_truncated,
        )
        flags: list[str] = []
        if conflicts:
            flags.append("CONFLICT_SURFACED")
        if chunk_injections or image_injections:
            flags.append("EMBEDDED_INJECTION_REMOVED")
        if view["masked"]:
            flags.append("PII_MASKED")
        if chart_rejection:
            flags.append("CHART_REJECTED")
        if (
            budget_info["truncated_source"]
            or budget_info["evidence_dropped_for_budget"]["count"]
        ):
            flags.append("EVIDENCE_TRIMMED_FOR_BUDGET")
        confidence = confidence_for(outcome, grounding["score"], top_relevance)
        total_ms = _ms(t_start)

        # A blocked injection attempt never becomes context for later turns.
        if not injection_blocked:
            self.memory.add(
                memory_key,
                Turn(
                    query_id=query_id,
                    query=req.query,
                    normalized=normalized,
                    answer=answer,
                    route=decision.route,
                ),
            )

        safety = {
            "query_injection": query_injection,
            "injection_blocked": injection_blocked,
            "chunk_injections": chunk_injections,
            "pii_detected": pii_detected,
            "pii_masked": view["masked"],
            "fallback": outcome != "success",
            "events": len(query_injection)
            + len(chunk_injections)
            + sum(view["masked"].values()),
        }

        usage.update(budget_info, budget={"max_input": max_in, "max_output": max_out})
        _finalize_usage(usage, settings)

        # Steps 10-11 — presentation + observability event
        event = {
            "identity": {
                "query_id": query_id,
                "timestamp": _now(),
                "session_id": session_id,
                "user_id": user.id,
                "username": user.username,
                "role": user.role,
                "app_version": settings.app_version,
                "config_id": req.config_id,
                "config_label": self.config_label(req.config_id),
                "correlation_id": correlation_id,
            },
            "question": {
                "original": req.query,
                "normalized": normalized,
                "route": decision.route,
                "data_signals": decision.data_signals,
                "doc_signals": decision.doc_signals,
                "router_notes": router_notes,
                "filters": {
                    "category": req.category,
                    "status": req.status,
                    "doc_id": req.doc_id,
                    "version": req.version,
                    "top_k": req.top_k,
                },
            },
            "execution": {"http_status": 200, "stages": stages},
            "outcome": {
                "status": outcome,
                "reason_codes": reasons,
                "flags": flags,
                "confidence": confidence,
            },
            "retrieval": [
                {
                    "chunk_id": c.chunk["chunk_id"],
                    "document_id": c.chunk["document_id"],
                    "filename": c.chunk["document_filename"],
                    "doc_id": c.chunk["doc_id"],
                    "version": c.chunk.get("version"),
                    "status": c.chunk.get("status"),
                    "category": c.chunk.get("category"),
                    "page": c.chunk.get("page"),
                    "section": c.chunk.get("section"),
                    "vector_score": c.vector_score,
                    "vector_rank": c.vector_rank,
                    "bm25_score": c.bm25_score,
                    "bm25_rank": c.bm25_rank,
                    "fused_score": c.fused_score,
                    "fused_rank": c.fused_rank,
                    "rerank_score": c.rerank_score,
                    "coverage": c.coverage,
                    "relevance": c.relevance,
                    "selected": c.selected,
                }
                for c in candidates[:15]
            ],
            "evidence": [ev.model_dump() for ev in evidence],
            "evidence_quality": {
                "evidence_found": evidence_found,
                "top_relevance": top_relevance,
                "threshold": min_rel,
                "expected_match": (eval_meta or {}).get("expected_match"),
            },
            "context": {
                "history_turns_available": len(history),
                "rewrite": {
                    "method": resolution.method,
                    "carried_terms": resolution.carried_terms,
                    "standalone": normalized if resolution.method != "none" else None,
                },
                "selected_turns": [
                    {"query_id": t.query_id, "query": t.query, "route": t.route}
                    for t in selected_turns
                ],
            },
            "tool_calls": [tc.model_dump() for tc in tool_calls],
            "generation": {**generation, "output": answer},
            "citations": [c.model_dump() for c in citations],
            "conflicts": conflicts,
            "calculations": calculations,
            "visuals": visuals,
            "chart_rejection": chart_rejection,
            "grounding": grounding,
            "safety": safety,
            "performance": {**perf, "total_ms": total_ms},
            "usage": usage,
            "errors": errors,
            "eval": eval_meta,
            "masking": {"applied": not user.is_admin, "counts": view["masked"]},
            "image_input": None
            if image is None
            else {
                "description": image.description,
                "used_text": image_text,
                "removed_instructions": image_injections,
                "model": image.model,
                "latency_ms": image.latency_ms,
                "size_bytes": image.size_bytes,
                "stored_path": image.stored_path,
            },
        }
        try:
            self.store.insert_event(event)
        except Exception:
            logger.exception("kis_event_persist_failed", query_id=query_id)

        logger.info(
            "kis_query_complete",
            query_id=query_id,
            outcome=outcome,
            reasons=reasons,
            route=decision.route,
            total_ms=total_ms,
        )
        return QueryResponse(
            query_id=query_id,
            session_id=session_id,
            answer=view["answer"],
            outcome=outcome,  # type: ignore[arg-type]
            reason_codes=reasons,
            flags=flags,
            confidence=confidence,  # type: ignore[arg-type]
            route=decision.route,  # type: ignore[arg-type]
            citations=citations,
            evidence=view["evidence"],
            tool_calls=view["tool_calls"],
            conflicts=view["conflicts"],
            safety=view["safety"](safety),
            grounding_score=grounding["score"],
            calculations=calculations,
            visuals=view["visuals"],
            usage={
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "estimated_input_tokens": usage["estimated_input_tokens"],
                "budget": usage["budget"],
            },
            latency_ms=total_ms,
            llm_mode="groq" if generation["provider"] == "groq" else "extractive",
        )

    @staticmethod
    def _present(
        answer: str,
        evidence: list[Evidence],
        tool_calls: list[ToolCall],
        conflicts: list[str],
        user: CurrentUser,
        visuals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """What this role may see. Admins: raw. Users: PII and salaries masked."""
        visuals = visuals or []
        public_tools = [
            tc.model_copy(update={"error_detail": None}) for tc in tool_calls
        ]
        if user.is_admin:
            return {
                "answer": answer,
                "evidence": evidence,
                "tool_calls": public_tools,
                "conflicts": conflicts,
                "masked": {},
                "safety": lambda s: s,
                "visuals": visuals,
            }
        counts: list[dict[str, int]] = []

        def mask(text: str) -> str:
            masked, found = mask_for_user(text)
            counts.append(found)
            return masked

        masked_answer = mask(answer)
        masked_evidence = [
            ev.model_copy(update={"content": mask(ev.content)}) for ev in evidence
        ]
        masked_tools = []
        for tc in public_tools:
            rows, found = mask_rows(tc.rows)
            counts.append(found)
            masked_tools.append(
                tc.model_copy(
                    update={"rows": rows, "result_summary": mask(tc.result_summary)}
                )
            )
        masked_conflicts = [mask(c) for c in conflicts]

        def safety_view(safety: dict[str, Any]) -> dict[str, Any]:
            injections = [
                {**ci, "removed_text": [mask(t) for t in ci.get("removed_text", [])]}
                for ci in safety["chunk_injections"]
            ]
            # Users do not see what PII the documents contain, only that some
            # of it was masked in their answer.
            hidden = {"pii_detected": None, "chunk_injections": injections}
            return {**safety, **hidden}

        # A generated chart drawn from a source that holds personal data or
        # salaries could reveal masked values, so users do not get it.
        sensitive = {ev.source_id for ev in evidence if detect_pii(ev.content)} | {
            tc.source_id for tc in tool_calls if mask_rows(tc.rows)[1]
        }
        safe_visuals = [
            v
            for v in visuals
            if v["kind"] != "generated_chart" or not set(v["source_ids"]) & sensitive
        ]
        return {
            "visuals": safe_visuals,
            "answer": masked_answer,
            "evidence": masked_evidence,
            "tool_calls": masked_tools,
            "conflicts": masked_conflicts,
            "masked": merge_counts(*counts),
            "safety": safety_view,
        }

    def _to_evidence(
        self, selected: list[Candidate], injections: list[dict[str, Any]]
    ) -> list[Evidence]:
        evidence = []
        for i, cand in enumerate(selected, start=1):
            c = cand.chunk
            clean = sanitize_evidence(c["content"])
            if clean.removed:
                injections.append(
                    {
                        "chunk_id": c["chunk_id"],
                        "filename": c["document_filename"],
                        "patterns": clean.patterns,
                        "removed_text": [s[:160] for s in clean.removed],
                        "action": "instruction removed; chunk kept as data",
                    }
                )
            evidence.append(
                Evidence(
                    source_id=f"S{i}",
                    chunk_id=c["chunk_id"],
                    document_id=c["document_id"],
                    filename=c["document_filename"],
                    doc_id=c["doc_id"],
                    title=c["title"],
                    category=c.get("category"),
                    version=c.get("version"),
                    status=c.get("status"),
                    page=c.get("page"),
                    section=c.get("section"),
                    content=clean.text,
                    content_type=c.get("content_type") or "text",
                    source_method=c.get("source_method") or "plain",
                    asset_id=c.get("asset_id"),
                    bbox=c.get("bbox"),
                    vector_score=cand.vector_score,
                    vector_rank=cand.vector_rank,
                    bm25_score=cand.bm25_score,
                    bm25_rank=cand.bm25_rank,
                    fused_score=cand.fused_score,
                    fused_rank=cand.fused_rank,
                    rerank_score=cand.rerank_score,
                    relevance=cand.relevance,
                    injection_flag=bool(clean.removed),
                )
            )
        return evidence

    # ── Feedback ─────────────────────────────────────────────

    # ── Per-user analytics (admin) and own history (user) ────

    def anomalies(self, since_hours: float = 24) -> list[dict[str, Any]]:
        since = (datetime.now(UTC) - timedelta(days=8)).isoformat(
            timespec="milliseconds"
        )
        return detect_anomalies(
            self.store.list_events(since=since, include_eval=False),
            self.store.list_auth_events(since=since),
            self.settings,
            since_hours=since_hours,
        )

    def user_summaries(self) -> list[dict[str, Any]]:
        flags: dict[str, set[str]] = {}
        for finding in self.anomalies(24):
            key = finding.get("user_id") or finding.get("username") or ""
            flags.setdefault(key, set()).add(finding["rule"])
        events = self.store.list_events(include_eval=False)
        sessions = self.store.list_sessions()
        out = []
        for user in self.store.list_users():
            evs = [e for e in events if e["identity"].get("user_id") == user["id"]]
            outcomes = Counter(e["outcome"]["status"] for e in evs)
            usage = [e.get("usage") or {} for e in evs]
            out.append(
                {
                    **user,
                    "queries": len(evs),
                    "sessions": sum(1 for x in sessions if x["user_id"] == user["id"]),
                    "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
                    "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
                    "cost_usd": round(
                        sum(u.get("estimated_cost_usd", 0) for u in usage), 6
                    ),
                    "outcomes": {
                        k: outcomes.get(k, 0) for k in ("success", "partial", "failed")
                    },
                    "safety_events": sum(1 for e in evs if e["safety"].get("events")),
                    "last_active": evs[0]["identity"]["timestamp"] if evs else None,
                    "anomalies": sorted(
                        flags.get(user["id"], set())
                        | flags.get(user["username"], set())
                    ),
                }
            )
        return out

    def session_rows(self, user_id: str, *, masked: bool) -> list[dict[str, Any]]:
        """Sessions with token totals. ``masked`` hides PII in the preview text."""
        events = self.store.list_events(user_id=user_id, include_eval=False)
        rows = []
        for sess in self.store.list_sessions(user_id):
            evs = [
                e for e in events if e["identity"]["session_id"] == sess["session_id"]
            ]
            if not evs:
                continue
            first = evs[-1]["question"]["original"]
            rows.append(
                {
                    **sess,
                    "title": mask_for_user(first)[0] if masked else first,
                    "input_tokens": sum(
                        (e.get("usage") or {}).get("input_tokens", 0) for e in evs
                    ),
                    "output_tokens": sum(
                        (e.get("usage") or {}).get("output_tokens", 0) for e in evs
                    ),
                    "cost_usd": round(
                        sum(
                            (e.get("usage") or {}).get("estimated_cost_usd", 0)
                            for e in evs
                        ),
                        6,
                    ),
                }
            )
        return rows

    def transcript(
        self, session_id: str, *, masked: bool, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """A session's turns, oldest first. Users get answers re-masked."""
        events = self.store.list_events(session_id=session_id, user_id=user_id)
        turns = []
        for e in reversed(events):
            answer = e["generation"].get("output") or ""
            usage = e.get("usage") or {}
            turns.append(
                {
                    "query_id": e["identity"]["query_id"],
                    "timestamp": e["identity"]["timestamp"],
                    "username": e["identity"].get("username"),
                    "query": mask_for_user(e["question"]["original"])[0]
                    if masked
                    else e["question"]["original"],
                    "answer": mask_for_user(answer)[0] if masked else answer,
                    "outcome": e["outcome"]["status"],
                    "reason_codes": e["outcome"]["reason_codes"],
                    "citations": len(e.get("citations") or []),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cost_usd": usage.get("estimated_cost_usd", 0),
                    "feedback": e.get("feedback"),
                }
            )
        return turns

    def add_feedback(
        self,
        query_id: str,
        helpful: bool,
        comment: str | None,
        user_id: str | None = None,
    ) -> bool:
        clean = comment.strip()[:1000] if comment else None
        return self.store.add_feedback(query_id, helpful, clean, _now(), user_id)


def _finalize_usage(usage: dict[str, Any], settings: Settings) -> None:
    """Totals across stages and the estimated cost from configured prices."""
    stages = usage["by_stage"].values()
    usage["input_tokens"] = sum(s.get("input_tokens", 0) for s in stages)
    usage["output_tokens"] = sum(s.get("output_tokens", 0) for s in stages)
    usage["estimated_cost_usd"] = round(
        usage["input_tokens"] / 1000 * settings.llm_price_input_per_1k
        + usage["output_tokens"] / 1000 * settings.llm_price_output_per_1k,
        8,
    )


def _doc_fields(row: dict[str, Any]) -> dict[str, Any]:
    keys = DocumentInfo.model_fields.keys()
    return {k: row.get(k) for k in keys}

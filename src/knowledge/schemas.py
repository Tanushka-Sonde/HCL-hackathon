"""Pydantic schemas for the knowledge service API and query event store."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ConfigId = Literal["A", "B"]
Outcome = Literal["success", "partial", "failed"]
Route = Literal["docs", "sql_tool", "both"]


# ── Requests ─────────────────────────────────────────────────


class QueryRequest(BaseModel):
    """Ask the assistant a question."""

    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)
    config_id: ConfigId = "B"
    top_k: int = Field(default=5, ge=1, le=10)
    category: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, max_length=20)
    doc_id: str | None = Field(default=None, max_length=60)
    version: str | None = Field(default=None, max_length=20)
    # Token budgets; the server also applies KIS_MAX_*_TOKENS_CAP.
    max_input_tokens: int = Field(default=3000, ge=256, le=32_000)
    max_output_tokens: int = Field(default=500, ge=32, le=4096)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: Literal["admin", "user"] = "user"


class FeedbackRequest(BaseModel):
    """Helpful / not-helpful feedback on a query (FR-11)."""

    query_id: str = Field(min_length=1, max_length=64)
    helpful: bool
    comment: str | None = Field(default=None, max_length=1000)


class EvalRunRequest(BaseModel):
    """Run the fixed evaluation set under one or more configurations."""

    configs: list[ConfigId] = Field(default_factory=lambda: ["A", "B"])


# ── Building blocks ──────────────────────────────────────────


class Evidence(BaseModel):
    """A retrieved chunk presented to the model, with all retrieval scores."""

    source_id: str
    chunk_id: str
    document_id: str
    filename: str
    doc_id: str
    title: str
    category: str | None = None
    version: str | None = None
    status: str | None = None
    page: int | None = None
    section: str | None = None
    content: str
    content_type: str = "text"
    source_method: str = "plain"
    asset_id: str | None = None
    bbox: list[float] | None = None
    vector_score: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    fused_score: float | None = None
    fused_rank: int | None = None
    rerank_score: float | None = None
    relevance: float = 0.0
    injection_flag: bool = False


class ToolCall(BaseModel):
    """A structured-data tool execution with provenance."""

    source_id: str
    name: str
    template: str
    params: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "error", "skipped"]
    row_count: int = 0
    latency_ms: float = 0.0
    result_summary: str = ""
    rows: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    error_detail: str | None = None
    simulated_failure: bool = False


class Citation(BaseModel):
    """A citation tag found in the answer, validated against evidence."""

    source_id: str
    valid: bool
    target: str | None = None
    page: int | None = None
    section: str | None = None


# ── Response ─────────────────────────────────────────────────


class QueryResponse(BaseModel):
    """What the chat UI shows for one turn."""

    query_id: str
    session_id: str
    answer: str
    outcome: Outcome
    reason_codes: list[str]
    flags: list[str]
    confidence: Literal["high", "medium", "low"]
    route: Route
    citations: list[Citation]
    evidence: list[Evidence]
    tool_calls: list[ToolCall]
    conflicts: list[str]
    safety: dict[str, Any]
    grounding_score: float | None
    calculations: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float
    llm_mode: Literal["groq", "extractive"]


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: Literal["admin", "user"]
    expires_in_minutes: int


class UserInfo(BaseModel):
    """Public user fields. There is deliberately no password field."""

    id: str
    username: str
    role: Literal["admin", "user"]
    is_active: bool
    created_at: str


class DocumentInfo(BaseModel):
    """Indexed document metadata."""

    id: str
    filename: str
    doc_id: str
    title: str
    category: str | None
    version: str | None
    status: str | None
    effective_date: str | None
    mime_type: str
    size_bytes: int
    pages: int | None
    chunk_count: int
    created_at: str
    uploaded_by: str | None = None
    vision_input_tokens: int = 0
    vision_output_tokens: int = 0


class IngestResponse(BaseModel):
    """Result of ingesting one file."""

    document: DocumentInfo
    duplicate: bool = False
    skipped_pages: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DemoIngestResponse(BaseModel):
    """Result of loading the bundled demo corpus."""

    ingested: list[IngestResponse]
    errors: list[dict[str, str]]

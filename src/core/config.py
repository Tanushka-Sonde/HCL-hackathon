"""Application configuration via environment variables.

Uses pydantic-settings to validate and type-check all configuration
at startup. Missing required values fail fast with clear error messages.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All values have sensible defaults for local development.
    Production deployments must override secrets via environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/research_platform"
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30
    database_pool_recycle: int = 1800

    # ── Object Storage ────────────────────────────────────────
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_name: str = "research-documents"
    minio_secure: bool = False

    # ── Redis ─────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # ── Authentication ────────────────────────────────────────
    jwt_secret_key: str = "change-me-to-a-random-256-bit-hex-string"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # ── External APIs ─────────────────────────────────────────
    google_api_key: str = ""
    tavily_api_key: str = ""
    groq_api_key: str = ""
    groq_model_name: str = "llama-3.1-8b-instant"

    # ── LLM Gateway ──────────────────────────────────────────
    llm_model_name: str = "models/gemini-2.0-flash"
    llm_rate_limit_rpm: int = 15
    llm_concurrency_limit: int = 5
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 3

    # ── Embedding ─────────────────────────────────────────────
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # ── Retrieval ─────────────────────────────────────────────
    retrieval_top_k: int = 5
    retrieval_candidate_multiplier: int = 2

    # ── Chunking ──────────────────────────────────────────────
    chunking_strategy: str = "semantic"
    chunking_semantic_threshold_percentile: float = 60.0
    chunking_semantic_buffer_size: int = 1

    # ── Ingestion Worker ──────────────────────────────────────
    worker_poll_interval_seconds: float = 1.0
    worker_max_concurrent_jobs: int = 2
    worker_stale_claim_timeout_minutes: int = 10

    # ── Knowledge Intelligence Service (local demo mode) ──────
    # demo_mode runs the self-contained knowledge assistant (SQLite + in-process
    # hybrid retrieval) without PostgreSQL, MinIO, Redis or Google OAuth.
    demo_mode: bool = True
    kis_data_dir: str = "data"
    kis_max_upload_mb: int = 20
    kis_chunk_size: int = 800
    kis_chunk_overlap: int = 120
    kis_embedder: str = "sentence-transformers"  # or "hashing"
    kis_reranker: str = "cross-encoder"  # or "lexical"
    kis_reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    kis_min_evidence_score: float = 0.6
    kis_grounding_threshold: float = 0.7
    kis_context_turns: int = 3
    kis_token_expire_minutes: int = 480  # demo-mode login lifetime
    llm_price_input_per_1k: float = 0.00005
    llm_price_output_per_1k: float = 0.00008
    prompt_template_version: str = "kis-grounded-v1"

    # ── Server ────────────────────────────────────────────────
    app_name: str = "AI Research Platform"
    app_version: str = "0.1.0"
    app_env: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @property
    def is_production(self) -> bool:
        """True when running in production environment."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """True when running in development environment."""
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings.

    Override in tests via FastAPI dependency_overrides:
        app.dependency_overrides[get_settings] = lambda: test_settings
    """
    return Settings()

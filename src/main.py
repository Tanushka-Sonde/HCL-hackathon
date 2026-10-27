"""FastAPI application factory.

Creates the app with lifespan management, error handling,
CORS middleware, health endpoints, and API routers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import prometheus_client
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.config import Settings, get_settings
from src.core.database import Database
from src.core.exceptions import AppError
from src.core.logging import configure_logging, get_logger
from src.core.rate_limit import close_rate_limiter, init_rate_limiter

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown.

    Startup: configure logging, create database engine.
    Shutdown: dispose database connections.
    """
    settings: Settings = get_settings()
    configure_logging(settings.log_level, settings.is_production)
    app.state.settings = settings

    if settings.demo_mode:
        # Local demo mode: the knowledge service uses SQLite and in-process
        # indexes, so PostgreSQL and Redis are not started.
        app.state.db = None
        # Load models and the index before serving, so the first request
        # does not time out behind the frontend proxy.
        import asyncio

        from src.knowledge.routes import get_service

        await asyncio.to_thread(get_service)
        logger.info("app_started", app_name=settings.app_name, mode="local-demo")
        yield
        logger.info("app_stopped")
        return

    db = Database(settings)
    app.state.db = db
    app.state.settings = settings

    logger.info(
        "app_started",
        app_name=settings.app_name,
        version=settings.app_version,
        env=settings.app_env,
    )
    # Initialize database engine
    engine = db.engine

    # Initialize redis rate limiter
    init_rate_limiter(settings.redis_url)

    yield

    # Cleanup resources on shutdown
    await close_rate_limiter()
    await db.dispose()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Multi-tenant AI Research Platform with hybrid retrieval",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    _register_middleware(app, settings)
    _register_error_handlers(app)
    _register_health_routes(app)
    _register_api_routers(app, settings)

    # Internal metrics endpoint
    app.mount("/metrics", prometheus_client.make_asgi_app())

    return app


# ── Middleware ───────────────────────────────────────────────


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    from src.observability.middleware import PrometheusMiddleware, RequestIdMiddleware

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    # Added last means it is outermost in Starlette
    app.add_middleware(PrometheusMiddleware)


# ── Error Handlers ──────────────────────────────────────────


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error",
            code=exc.code,
            status=exc.status_code,
            message=exc.message,
            path=str(request.url),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_exception",
            path=str(request.url),
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred.",
                }
            },
        )


# ── Health ───────────────────────────────────────────────────


def _register_health_routes(app: FastAPI) -> None:
    @app.get("/health", tags=["health"])
    async def health_shallow() -> dict[str, str]:
        """Shallow health check — process is alive."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def health_ready(request: Request) -> JSONResponse:
        """Deep health check — database and services reachable."""
        checks: dict[str, str] = {}
        if request.app.state.settings.demo_mode:
            from src.knowledge.routes import get_service

            try:
                svc = get_service()
                svc.store.list_documents()
                checks["knowledge_store"] = "ok"
                checks["business_db"] = "ok" if svc.tool.departments else "missing"
                details = svc.describe()
            except Exception as exc:
                checks["knowledge_store"] = f"error: {type(exc).__name__}"
                details = {}
            overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
            return JSONResponse(
                status_code=200 if overall == "ok" else 503,
                content={
                    "status": overall,
                    "mode": "local-demo",
                    "checks": checks,
                    "embedder": details.get("embedder"),
                    "reranker": details.get("reranker"),
                    "llm": details.get("llm_provider"),
                    "indexed_chunks": details.get("indexed_chunks"),
                },
            )

        db: Database = request.app.state.db

        try:
            async with db.session_factory() as session:
                await session.execute(__import__("sqlalchemy").text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        status_code = 200 if overall == "ok" else 503
        return JSONResponse(
            status_code=status_code,
            content={"status": overall, "checks": checks},
        )


# ── Routers ──────────────────────────────────────────────────


def _register_api_routers(app: FastAPI, settings: Settings) -> None:
    if settings.demo_mode:
        # Local demo mode exposes only the knowledge service. It has no user
        # accounts; the UI labels it "Local demo mode". The production routers
        # below (OAuth, tenants, PostgreSQL) are not mounted.
        from src.knowledge.routes import router as knowledge_router

        app.include_router(knowledge_router, prefix=settings.api_prefix)
        return

    from src.auth.routes import router as auth_router
    from src.documents.routes import router as documents_router
    from src.evaluation.routes import router as evaluation_router
    from src.ingestion.routes import router as ingestion_router
    from src.retrieval.routes import router as search_router
    from src.tenants.routes import router as tenants_router
    from src.auth.dependencies import get_current_user
    from fastapi import Depends

    # Auth router handles its own dependencies internally for /me and /api-keys
    app.include_router(auth_router, prefix=settings.api_prefix)

    # Globally enforce authentication for all other routers
    auth_dep = [Depends(get_current_user)]
    app.include_router(tenants_router, prefix=settings.api_prefix, dependencies=auth_dep)
    app.include_router(documents_router, prefix=settings.api_prefix, dependencies=auth_dep)
    app.include_router(ingestion_router, prefix=settings.api_prefix, dependencies=auth_dep)
    app.include_router(search_router, prefix=settings.api_prefix, dependencies=auth_dep)
    app.include_router(evaluation_router, prefix=settings.api_prefix, dependencies=auth_dep)


# Module-level app instance for `uvicorn src.main:app`
app = create_app()

"""Fixtures for the knowledge service tests (no PostgreSQL / network needed).

Uses the deterministic hashing embedder, lexical reranker and extractive
generator so results are repeatable and offline.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import Settings  # noqa: E402
from src.knowledge.service import KnowledgeService  # noqa: E402


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Copy of demo/ with the binary corpus files built."""
    target = tmp_path_factory.mktemp("demo")
    shutil.copytree(ROOT / "demo", target, dirs_exist_ok=True)
    corpus = target / "corpus"
    if not (corpus / "TRV-POL-003_Travel_Expense_Policy.pdf").exists():
        from scripts.build_demo import (
            TRAVEL_PAGES,
            write_procurement_docx,
            write_text_pdf,
        )

        write_text_pdf(corpus / "TRV-POL-003_Travel_Expense_Policy.pdf", TRAVEL_PAGES)
        write_procurement_docx(corpus / "FIN-SOP-045_Procurement_SOP.docx")
    return target


@pytest.fixture(scope="session")
def offline_settings() -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=True,
        kis_embedder="hashing",
        kis_reranker="lexical",
        groq_api_key="",
    )


@pytest.fixture(scope="session")
def service(
    tmp_path_factory: pytest.TempPathFactory, offline_settings: Settings, demo_dir: Path
) -> KnowledgeService:
    svc = KnowledgeService(
        offline_settings, data_dir=tmp_path_factory.mktemp("data"), demo_dir=demo_dir
    )
    result = svc.ingest_demo()
    assert not result.errors, result.errors
    return svc


@pytest.fixture(scope="session")
def client(service: KnowledgeService, offline_settings: Settings) -> TestClient:
    import src.knowledge.routes as routes
    from src.core.config import get_settings
    from src.main import create_app

    routes._service = service  # startup warm-up uses the test service too
    app = create_app()
    app.dependency_overrides[routes.get_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: offline_settings
    with TestClient(app) as c:
        yield c

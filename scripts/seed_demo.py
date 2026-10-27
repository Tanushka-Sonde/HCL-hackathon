"""Index the synthetic demo corpus into the local knowledge store.

Usage:  python scripts/seed_demo.py
(Run scripts/build_demo.py first to generate the PDF/DOCX files.)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import get_settings  # noqa: E402
from src.knowledge.service import KnowledgeService  # noqa: E402


def main() -> None:
    svc = KnowledgeService(get_settings())
    created = svc.auth.ensure_demo_users()
    if created:
        print(f"Created demo accounts: {', '.join(created)}")
        print("  admin / admin123 (admin), alice / user123, bob / user123 (users)")
    result = svc.ingest_demo()
    for item in result.ingested:
        d = item.document
        tag = "already indexed" if item.duplicate else f"{d.chunk_count} chunks"
        print(
            f"  {d.filename:<50} {d.doc_id:<12} v{d.version or '-':<5} {d.status or '-':<11} {tag}"
        )
    for err in result.errors:
        print(f"  ERROR {err['filename']}: {err['error']}")
    print(
        f"Embedder: {svc.embedder_name} | Reranker: {svc.reranker.name} | Chunks indexed: {len(svc.index)}"
    )


if __name__ == "__main__":
    main()

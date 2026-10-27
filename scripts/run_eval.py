"""Run the A/B configuration experiment on the fixed evaluation set.

Writes reports/evaluation_report.md and prints the summary table.

Usage:  python scripts/run_eval.py [A B]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import get_settings  # noqa: E402
from src.knowledge.evaluation import REPORT_PATH, run_evaluation  # noqa: E402
from src.knowledge.service import KnowledgeService  # noqa: E402


def main() -> None:
    configs = [c for c in sys.argv[1:] if c in ("A", "B")] or ["A", "B"]
    svc = KnowledgeService(get_settings())
    if not len(svc.index):
        svc.ingest_demo()
    results = asyncio.run(run_evaluation(svc, configs))
    for cfg, data in results["configs"].items():
        print(f"\n[{cfg}] {data['label']}")
        for key, value in data["summary"].items():
            print(f"  {key:<24} {value}")
    print(f"\nReport written to {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

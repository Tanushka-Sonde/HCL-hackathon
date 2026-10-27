"""Run the configuration experiment (A, B and the ablation C) on the evaluation set.

Writes reports/evaluation_report.md and prints the summary table.

Usage:  python scripts/run_eval.py [A B C]
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
    configs = [c for c in sys.argv[1:] if c in ("A", "B", "C")] or ["A", "B", "C"]
    svc = KnowledgeService(get_settings())
    if not len(svc.index):
        svc.ingest_demo()
    results = asyncio.run(run_evaluation(svc, configs))
    for cfg, data in results["configs"].items():
        print(f"\n[{cfg}] {data['label']}")
        for key, value in data["summary"].items():
            if key != "by_scenario":
                print(f"  {key:<24} {value}")
    if results.get("recommendation"):
        rec = results["recommendation"]
        print(f"\nRecommendation: {rec['config']} - {rec['why']}")
    print(f"\nReport written to {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

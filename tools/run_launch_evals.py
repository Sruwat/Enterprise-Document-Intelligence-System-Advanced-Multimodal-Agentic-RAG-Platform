from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dependencies import get_app_settings, get_evaluation_service


def main() -> None:
    args = _parse_args()
    settings = get_app_settings()
    dataset = Path(args.dataset or settings.data_dir / "eval_dataset_aiwana_launch.json")
    service = get_evaluation_service()
    result = service.run_seeded_evaluation(str(dataset), query_limit=args.query_limit)
    gates = service.launch_gates(
        dataset_path=str(dataset),
        min_queries=0,
        min_benchmark_pass_rate=args.min_pass_rate,
        min_category_pass_rate=args.min_category_pass_rate,
        require_dataset_coverage=True,
    )
    payload = {"evaluation": result, "gates": gates}
    print(json.dumps(payload, indent=2, default=str))
    if gates.get("status") != "ready":
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Aiwana launch seeded evaluation and enforce launch gates.")
    parser.add_argument("--dataset", help="Dataset path. Defaults to data/eval_dataset_aiwana_launch.json.")
    parser.add_argument("--query-limit", type=int, default=None, help="Optional limit for a smoke subset.")
    parser.add_argument("--min-pass-rate", type=float, default=0.8)
    parser.add_argument("--min-category-pass-rate", type=float, default=0.75)
    return parser.parse_args()


if __name__ == "__main__":
    main()

"""Repeatable local query-mode benchmark.

The script intentionally measures an HTTP endpoint when a live stack is
available, and always writes raw samples so p50/p95/p99 claims are auditable.
It never fabricates missing provider timings.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path
from urllib import request


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("AIWANA_API_BASE", "http://localhost:8000"))
    parser.add_argument("--workspace", default=os.getenv("AIWANA_SMOKE_WORKSPACE", "default"))
    parser.add_argument("--question", default="Summarize the main obligations and cite the source pages.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--token", default=os.getenv("AIWANA_SMOKE_TOKEN", ""))
    parser.add_argument("--output", default="data/benchmarks/query_modes.json")
    args = parser.parse_args()
    results = {"base": args.base, "workspace_id": args.workspace, "question": args.question, "runs": args.runs, "modes": {}}
    for mode in ("fast", "balanced", "deep", "auto"):
        samples = []
        for _ in range(max(1, args.runs)):
            payload = json.dumps({"question": args.question, "workspace_id": args.workspace, "query_mode": mode, "return_evidence_canvas": True}).encode()
            req = request.Request(f"{args.base.rstrip('/')}/query", data=payload, headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {args.token}"} if args.token else {})})
            started = time.perf_counter()
            try:
                with request.urlopen(req, timeout=180) as response:
                    body = json.loads(response.read().decode())
                elapsed = (time.perf_counter() - started) * 1000
                samples.append({"total_ms": round(elapsed, 2), "latency_ms": body.get("latency_ms", {}), "grounding_status": body.get("grounding_status")})
            except Exception as exc:
                samples.append({"error": str(exc), "total_ms": round((time.perf_counter() - started) * 1000, 2)})
        successful = [item["total_ms"] for item in samples if "error" not in item]
        results["modes"][mode] = {"samples": samples, "p50_ms": percentile(successful, 0.50), "p95_ms": percentile(successful, 0.95), "p99_ms": percentile(successful, 0.99), "successful_runs": len(successful), "avg_ms": round(statistics.mean(successful), 2) if successful else None}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0 if any(item["successful_runs"] for item in results["modes"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())

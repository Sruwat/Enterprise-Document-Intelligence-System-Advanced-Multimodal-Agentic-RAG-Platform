from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dependencies import get_huggingface_registry


def main() -> int:
    registry = get_huggingface_registry()
    before = registry.status()
    samples = {
        "entity_extraction": "NovaTech signed the Alpha Agreement with River Labs.",
        "document_classification": "This agreement contains termination and liability clauses.",
        "evidence_checking": "NovaTech signed the Alpha Agreement.",
    }
    results = {}
    for task, payload in samples.items():
        started = time.perf_counter()
        provider = registry.provider_for(task)
        results[task] = provider.run(payload)
        results[task]["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    after = registry.status()
    print(json.dumps({"before": before, "results": results, "after": after}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

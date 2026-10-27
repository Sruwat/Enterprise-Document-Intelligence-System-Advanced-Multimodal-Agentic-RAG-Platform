from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.storage.qdrant import QdrantVectorStore


def main() -> None:
    settings = get_settings()
    store = QdrantVectorStore(
        settings.qdrant_url,
        settings.qdrant_collection,
        fallback_url=None,
        use_named_vectors=settings.enable_named_vectors,
        use_sparse_vectors=settings.enable_bge_m3_sparse,
    )
    vector_size = 1024 if "bge-m3" in settings.embedding_model.lower() else 384
    report = store.verify_collection(vector_size)
    report["filter_probe"] = store.verify_server_side_filters(vector_size)
    report["ok"] = bool(report.get("ok") and report["filter_probe"].get("ok"))
    print(json.dumps(report, indent=2, default=str))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

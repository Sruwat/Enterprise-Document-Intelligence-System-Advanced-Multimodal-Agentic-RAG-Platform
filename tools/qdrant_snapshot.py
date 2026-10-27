from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dependencies import get_app_settings
from app.storage.qdrant import QdrantVectorStore


def main() -> None:
    args = _parse_args()
    settings = get_app_settings()
    store = QdrantVectorStore(
        settings.qdrant_url,
        settings.qdrant_collection,
        fallback_url=None,
        use_named_vectors=settings.enable_named_vectors,
        use_sparse_vectors=settings.enable_bge_m3_sparse,
    )
    if args.command == "create":
        result = store.create_snapshot()
    elif args.command == "list":
        result = store.list_snapshots()
    elif args.command == "restore":
        snapshots = store.list_snapshots()
        names = {snapshot.get("name") for snapshot in snapshots.get("snapshots", []) if isinstance(snapshot, dict)}
        validation = {
            "status": "ok" if args.snapshot in names or args.snapshot.startswith(("http://", "https://", "file://")) else "blocked",
            "collection": settings.qdrant_collection,
            "snapshot": args.snapshot,
            "known_snapshots": sorted(name for name in names if name),
            "dry_run": args.dry_run,
        }
        if validation["status"] != "ok" or args.dry_run:
            result = validation
        else:
            result = store.restore_snapshot(args.snapshot)
    else:
        raise SystemExit(f"Unknown command: {args.command}")
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") == "blocked":
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create, list, or restore Qdrant collection snapshots.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create", help="Create a snapshot for the configured collection.")
    subparsers.add_parser("list", help="List snapshots for the configured collection.")
    restore = subparsers.add_parser("restore", help="Validate or restore a snapshot.")
    restore.add_argument("--snapshot", required=True, help="Snapshot name or URL/path accepted by Qdrant recover_snapshot.")
    restore.add_argument("--dry-run", action="store_true", help="Validate snapshot availability without restoring.")
    return parser.parse_args()


if __name__ == "__main__":
    main()

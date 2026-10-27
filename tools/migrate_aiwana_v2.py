from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.core.dependencies import get_bm25_store, get_embedding_provider, get_indexer, get_metadata_store, get_vector_store


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    metadata_store = get_metadata_store()
    embedder = get_embedding_provider()
    launch_profile = "bge-m3" in settings.embedding_model.lower() and "v2" in settings.qdrant_collection.lower()
    if args.reingest and not launch_profile:
        raise SystemExit(
            "Refusing to re-ingest because the active profile is not BGE-M3 + aiwana_chunks_v2. "
            "Update .env or pass the correct environment variables before running --reingest."
        )
    status = embedder.status()
    dimension = int(status.get("dimension") or 0)
    expected = int(status.get("expected_dimension") or dimension or 0)
    if "bge-m3" in settings.embedding_model.lower() and dimension != 1024:
        raise SystemExit(f"Embedding dimension mismatch: expected 1024 for BGE-M3, got {dimension or 'unavailable'}.")
    if dimension and expected and dimension != expected:
        raise SystemExit(f"Embedding dimension mismatch: expected {expected}, got {dimension}. Recheck {settings.embedding_model_path}.")

    documents = metadata_store.list_documents(workspace_id=args.workspace_id)
    if args.status:
        documents = [document for document in documents if document.status in set(args.status)]
    if args.limit:
        documents = documents[: args.limit]
    duplicate_groups = _duplicate_fingerprint_groups(documents)

    print("Aiwana v2 migration")
    print(f"- metadata db: {metadata_store.db_path}")
    print(f"- qdrant collection: {settings.qdrant_collection}")
    print(f"- qdrant url: {settings.qdrant_url}")
    print(f"- embedding model: {settings.embedding_model}")
    print(f"- embedding dimension: {dimension or 'unavailable'}")
    print(f"- launch profile active: {'yes' if launch_profile else 'no'}")
    print(f"- candidate documents: {len(documents)}")
    if duplicate_groups:
        print(f"- duplicate fingerprint groups: {len(duplicate_groups)}")
        for fingerprint, grouped in list(duplicate_groups.items())[:10]:
            print(f"  - {fingerprint[:12]}: keeping {grouped[0].document_id}, duplicate records {[doc.document_id for doc in grouped[1:]]}")

    missing = [document for document in documents if not Path(document.source_path).is_file()]
    if missing:
        print(f"- skipped missing source files: {len(missing)}")
        for document in missing[:10]:
            print(f"  - {document.document_id}: {document.source_path}")
    ready = [document for document in documents if Path(document.source_path).is_file()]
    if args.dry_run or not args.reingest:
        _print_reconciliation(metadata_store, get_vector_store(), documents)
        print("- dry run only: pass --reingest to rebuild vectors and chunks in the v2 collection.")
        return

    vector_store = get_vector_store()
    if args.dedupe_duplicates and duplicate_groups:
        removed = _dedupe_duplicate_documents(metadata_store, vector_store, get_bm25_store(), duplicate_groups)
        print(f"- removed duplicate document records before re-ingest: {removed}")
        documents = metadata_store.list_documents(workspace_id=args.workspace_id)
        if args.status:
            documents = [document for document in documents if document.status in set(args.status)]
        ready = [document for document in documents if Path(document.source_path).is_file()]
    if dimension:
        vector_store.ensure_collection(dimension)
    active_location = vector_store.get_active_location()
    if active_location.startswith("file://") and not args.allow_local_fallback:
        raise SystemExit(
            f"Refusing to re-ingest into local file fallback ({active_location}). "
            "Start Qdrant server or pass --allow-local-fallback for a local-only test migration."
        )
    print(f"- qdrant location: {active_location}")
    _print_reconciliation(metadata_store, vector_store, documents)
    indexer = get_indexer()
    succeeded = 0
    failed = 0
    for document in ready:
        objective_profile = (document.metadata or {}).get("objective_profile", "general")
        try:
            response = indexer.ingest_source(
                document.source_path,
                workspace_id=document.workspace_id,
                objective_profile=objective_profile,
                force_reindex=True,
            )
            succeeded += 1
            print(f"- reindexed {document.filename}: {response.chunks_created} chunk(s)")
        except Exception as exc:
            failed += 1
            print(f"- failed {document.filename}: {exc}")

    print(f"Migration complete: {succeeded} succeeded, {failed} failed.")
    _print_reconciliation(metadata_store, vector_store, metadata_store.list_documents(workspace_id=args.workspace_id))
    _mark_legacy_collection(settings.qdrant_collection)
    if failed:
        raise SystemExit(1)


def _print_reconciliation(metadata_store, vector_store, documents) -> None:
    metadata_chunks = sum(len(metadata_store.list_chunks(document.document_id)) for document in documents)
    vector_count = vector_store.count()
    print(f"- metadata chunks for candidates: {metadata_chunks}")
    print(f"- qdrant vector points in active collection: {vector_count}")
    if metadata_chunks != vector_count:
        print(f"- reconciliation warning: metadata chunk count ({metadata_chunks}) differs from Qdrant point count ({vector_count}).")


def _mark_legacy_collection(active_collection: str) -> None:
    state_path = PROJECT_ROOT / "data" / "aiwana_migration_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    legacy = sorted({*state.get("legacy_collections", []), "rag_chunks"})
    state.update(
        {
            "active_collection": active_collection,
            "legacy_collections": legacy,
            "updated_at": datetime.utcnow().isoformat(),
            "rollback_note": "Legacy collections are retained until v2 retrieval is validated in production.",
        }
    )
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"- migration state updated: {state_path}")


def _duplicate_fingerprint_groups(documents) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for document in documents:
        if not document.fingerprint:
            continue
        key = f"{document.workspace_id}:{document.fingerprint}"
        grouped.setdefault(key, []).append(document)
    return {fingerprint: records for fingerprint, records in grouped.items() if len(records) > 1}


def _dedupe_duplicate_documents(metadata_store, vector_store, sparse_store, duplicate_groups: dict[str, list]) -> int:
    removed = 0
    for records in duplicate_groups.values():
        for duplicate in records[1:]:
            chunk_ids = metadata_store.delete_document(duplicate.document_id, duplicate.workspace_id)
            vector_store.delete(chunk_ids)
            sparse_store.remove_documents(chunk_ids)
            removed += 1
    return removed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and optionally re-index existing Aiwana documents into the v2 BGE-M3/Qdrant collection.")
    parser.add_argument("--workspace-id", help="Only migrate one workspace.")
    parser.add_argument("--status", action="append", choices=["indexed", "failed", "processing"], help="Only include documents with this status. Repeatable.")
    parser.add_argument("--limit", type=int, help="Only process the first N candidate documents.")
    parser.add_argument("--reingest", action="store_true", help="Force re-index existing source files into the configured v2 collection.")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be migrated.")
    parser.add_argument("--allow-local-fallback", action="store_true", help="Allow --reingest to use file:// local Qdrant fallback. Do not use for SaaS launch.")
    parser.add_argument("--dedupe-duplicates", action="store_true", help="Remove duplicate document records with the same workspace+fingerprint before re-ingest.")
    return parser.parse_args()


if __name__ == "__main__":
    main()

"""Enqueue/execute expired temporary-document purge without deleting in a request."""
from __future__ import annotations

import argparse

from app.core.dependencies import get_app_settings, get_bm25_store, get_graph_repository, get_metadata_store, get_query_cache, get_vector_store
from app.services.data_vault import DocumentPurgeService
from app.core.schemas import UserRecord
from datetime import datetime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="default-tenant")
    args = parser.parse_args()
    metadata = get_metadata_store()
    settings = get_app_settings()
    service = DocumentPurgeService(metadata_store=metadata, vector_store=get_vector_store(), sparse_store=get_bm25_store(), query_cache=get_query_cache(), graph_repository=get_graph_repository(), settings=settings)
    actor = UserRecord(user_id="system-retention", tenant_id=args.tenant, email="system-retention@aiwana.local", created_at=datetime.utcnow())
    jobs = service.purge_expired_temporary_documents(tenant_id=args.tenant, user=actor)
    print({"status": "ok", "purged_jobs": len(jobs), "jobs": [job.model_dump(mode="json") for job in jobs]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

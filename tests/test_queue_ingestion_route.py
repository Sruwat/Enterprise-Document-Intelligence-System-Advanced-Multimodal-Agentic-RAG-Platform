from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_context import hash_token
from app.api.routes.ingest import public_router
from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_indexer, get_metadata_store, get_redis_service, get_worker_queue
from app.services.worker import WorkerQueue
from app.storage.metadata_store import MetadataStore


class _UnusedIndexer:
    def ingest_source(self, *args, **kwargs):
        raise AssertionError("queue-first ingestion must not call the indexer in the request path")


def _app(store, settings, queue):
    app = FastAPI()
    app.include_router(public_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_redis_service] = lambda: None
    app.dependency_overrides[get_worker_queue] = lambda: queue
    app.dependency_overrides[get_indexer] = lambda: _UnusedIndexer()
    return app


def test_text_source_uses_worker_queue_when_enabled(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(
        REQUIRE_AUTH=True,
        ENABLE_LOCAL_USER_FALLBACK=False,
        DATABASE_BACKEND="sqlite",
        METADATA_DB=str(tmp_path / "metadata.db"),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        ENABLE_QUEUE_INGESTION=True,
    )
    owner = store.create_user("queue-owner@example.com", tenant_id="tenant-queue")
    workspace = store.create_workspace("Queue", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    token = "queue-owner-token"
    store.create_auth_session(hash_token(token), owner.user_id, datetime.utcnow().replace(year=2099))
    queue = WorkerQueue(redis_service=None)

    with TestClient(_app(store, settings, queue)) as client:
        response = client.post(
            f"/workspaces/{workspace.workspace_id}/sources/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "Queue Proof", "text": "This source should be indexed by the worker."},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["message"] == "Queued for background indexing."
    assert queue.status()["queued"] == 1

    persisted = store.get_ingestion_job(payload["job_id"])
    assert persisted is not None
    assert persisted.message == "Queued for background indexing."
    assert persisted.metadata["source_path"].endswith("Queue Proof.md")


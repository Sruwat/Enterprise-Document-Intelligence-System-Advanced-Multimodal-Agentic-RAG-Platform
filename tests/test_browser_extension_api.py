from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_context import hash_token
from app.api.routes.browser import router as browser_router
from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_metadata_store, get_redis_service, get_worker_queue
from app.services.auth.api_keys import ApiKeyService
from app.services.worker import WorkerQueue
from app.storage.metadata_store import MetadataStore


def _app(store, settings, queue):
    app = FastAPI()
    app.include_router(browser_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_redis_service] = lambda: None
    app.dependency_overrides[get_worker_queue] = lambda: queue
    return app


def _seed_owner(store):
    owner = store.create_user("owner@example.com", tenant_id="tenant-browser")
    workspace = store.create_workspace("Browser", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    token = "browser-owner-token"
    store.create_auth_session(hash_token(token), owner.user_id, datetime.utcnow().replace(year=2099))
    return owner, workspace, token


def test_browser_capture_sanitizes_and_queues_ingestion(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(
        REQUIRE_AUTH=True,
        ENABLE_LOCAL_USER_FALLBACK=False,
        DATABASE_BACKEND="sqlite",
        METADATA_DB=str(tmp_path / "metadata.db"),
        UPLOAD_DIR=str(tmp_path / "uploads"),
    )
    _, workspace, token = _seed_owner(store)
    queue = WorkerQueue(redis_service=None)

    with TestClient(_app(store, settings, queue)) as client:
        response = client.post(
            "/browser/capture",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "workspace_id": workspace.workspace_id,
                "title": "Aiwana Page",
                "url": "https://example.test/page",
                "text": "Aiwana Browser Capture. api_key=secret-value\n\nEnterprise RAG source.",
                "selection_used": True,
                "extension_version": "test",
            },
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["message"] == "Browser page queued for indexing."
    assert payload["metadata"]["source_type"] == "browser_page"
    assert queue.status()["queued"] == 1

    job = store.get_ingestion_job(payload["job_id"])
    assert job is not None
    source_text = Path(job.metadata["source_path"]).read_text(encoding="utf-8")
    assert "secret-value" not in source_text
    assert "api_key: [redacted]" in source_text


def test_browser_query_accepts_workspace_scoped_api_key(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(REQUIRE_AUTH=True, ENABLE_LOCAL_USER_FALLBACK=False, DATABASE_BACKEND="sqlite", METADATA_DB=str(tmp_path / "metadata.db"))
    owner, workspace, _ = _seed_owner(store)
    api_key = ApiKeyService(store).create_key(
        workspace=workspace,
        creator=owner,
        name="Extension",
        role="viewer",
        permissions=["workspace.read", "document.query"],
    ).api_key
    queue = WorkerQueue(redis_service=None)

    with TestClient(_app(store, settings, queue)) as client:
        response = client.post(
            "/browser/current-page/query",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "workspace_id": workspace.workspace_id,
                "title": "Revenue Memo",
                "url": "https://example.test/revenue",
                "question": "What does the memo say about revenue?",
                "text": "The revenue memo says revenue grew 24 percent. Expenses were flat.",
            },
        )

    assert response.status_code == 200
    assert "revenue grew 24 percent" in response.json()["summary"]

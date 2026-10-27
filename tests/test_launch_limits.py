from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.rate_limit import InMemoryRateLimitMiddleware
from app.api.routes.ingest import public_router as sources_router
from app.api.routes.workspaces import router as workspace_router
from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_indexer, get_metadata_store
from app.core.schemas import DocumentRecord, IngestResponse
from app.storage.metadata_store import MetadataStore


class _NoopIndexer:
    def ingest_source(self, path, workspace_id="default", progress_callback=None, objective_profile="general"):
        return IngestResponse(
            document=DocumentRecord(
                document_id="doc-source",
                workspace_id=workspace_id,
                filename=Path(path).name,
                source_path=str(path),
                fingerprint="fp",
                status="indexed",
                page_count=1,
                ingested_at=datetime.utcnow(),
            ),
            chunks_created=1,
            indexed=True,
        )


def _source_app(store: MetadataStore, settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(workspace_router)
    app.include_router(sources_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_indexer] = lambda: _NoopIndexer()
    return app


def test_upload_rejects_renamed_non_pdf(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        REQUIRE_AUTH=False,
        ENABLE_LOCAL_USER_FALLBACK=True,
        DATABASE_BACKEND="sqlite",
    )
    app = _source_app(store, settings)

    with TestClient(app) as client:
        workspace = client.post("/workspaces", json={"name": "Limits"}).json()
        response = client.post(
            f"/workspaces/{workspace['workspace_id']}/sources",
            files=[("files", ("fake.pdf", b"not actually a pdf", "application/pdf"))],
        )

    assert response.status_code == 415
    assert "valid PDF" in response.text


def test_upload_rejects_renamed_non_docx(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        REQUIRE_AUTH=False,
        ENABLE_LOCAL_USER_FALLBACK=True,
        DATABASE_BACKEND="sqlite",
    )
    app = _source_app(store, settings)

    with TestClient(app) as client:
        workspace = client.post("/workspaces", json={"name": "Contracts"}).json()
        response = client.post(
            f"/workspaces/{workspace['workspace_id']}/sources",
            files=[("files", ("fake.docx", b"not a zip package", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )

    assert response.status_code == 415
    assert "valid DOCX" in response.text


def test_workspace_document_quota_blocks_upload(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        MAX_WORKSPACE_DOCUMENTS=0,
        REQUIRE_AUTH=False,
        ENABLE_LOCAL_USER_FALLBACK=True,
        DATABASE_BACKEND="sqlite",
    )
    app = _source_app(store, settings)

    with TestClient(app) as client:
        workspace = client.post("/workspaces", json={"name": "Quota"}).json()
        response = client.post(
            f"/workspaces/{workspace['workspace_id']}/sources",
            files=[("files", ("notes.txt", b"hello", "text/plain"))],
        )

    assert response.status_code == 403
    assert "quota" in response.text.lower()


def test_rate_limit_middleware_blocks_bursts():
    app = FastAPI()
    app.add_middleware(InMemoryRateLimitMiddleware, enabled=True, requests=1, window_seconds=60)

    @app.get("/auth/probe")
    def probe():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/auth/probe").status_code == 200
        blocked = client.get("/auth/probe")

    assert blocked.status_code == 429

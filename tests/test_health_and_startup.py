from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.health import router as health_router
from app.api.startup import validate_startup
from app.core.config import Settings
from app.core.schemas import DocumentRecord
from app.storage.metadata_store import MetadataStore


class _FakeEmbeddingProvider:
    def status(self):
        return {"status": "ok", "path": "models/bge-small-en-v1.5", "loaded": True, "dimension": 384}

    def embed_query(self, _text):
        return [0.1] * 384


class _FakeReranker:
    model_name = "models/bge-reranker-base"

    def status(self):
        return {"status": "ok", "path": "models/bge-reranker-base", "loaded": True}


class _FakeLLM:
    provider_name = "grounded_fallback"
    model_name = "extractive-local-v1"


class _FakeVectorStore:
    def is_available(self):
        return True

    def get_active_location(self):
        return "file://./data/qdrant_local"

    def count(self):
        return 0


class _FakeBM25:
    def size(self):
        return 0


class _FakeRedis:
    def __init__(self, status="disabled"):
        self._status = status

    def status(self):
        return {"status": self._status, "enabled": self._status != "disabled", "url": "redis://test"}


def test_startup_validates_local_model_paths(monkeypatch, tmp_path):
    embedding_path = tmp_path / "models" / "bge-small-en-v1.5"
    reranker_path = tmp_path / "models" / "bge-reranker-base"
    embedding_path.mkdir(parents=True)
    reranker_path.mkdir(parents=True)

    settings = Settings(
        EMBEDDING_MODEL_PATH=str(embedding_path),
        RERANKER_MODEL_PATH=str(reranker_path),
        DATA_DIR=str(tmp_path / "data"),
        UPLOAD_DIR=str(tmp_path / "data" / "uploads"),
        LOG_DIR=str(tmp_path / "data" / "logs"),
        METADATA_DB=str(tmp_path / "data" / "metadata.db"),
    )
    store = MetadataStore(tmp_path / "data" / "metadata.db")

    monkeypatch.setattr("app.api.startup.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.startup.get_primary_llm", lambda: _FakeLLM())
    monkeypatch.setattr("app.api.startup.get_vector_store", lambda: _FakeVectorStore())
    monkeypatch.setattr("app.api.startup.get_embedding_provider", lambda: _FakeEmbeddingProvider())
    monkeypatch.setattr("app.api.startup.get_reranker", lambda: _FakeReranker())
    monkeypatch.setattr("app.api.startup.get_metadata_store", lambda: store)
    monkeypatch.setattr("app.api.startup.get_bm25_store", lambda: _FakeBM25())
    monkeypatch.setattr("app.api.startup.get_redis_service", lambda: _FakeRedis())

    validate_startup()


def test_health_endpoint_reports_actual_model_statuses(monkeypatch, tmp_path):
    embedding_path = tmp_path / "models" / "bge-small-en-v1.5"
    reranker_path = tmp_path / "models" / "bge-reranker-base"
    embedding_path.mkdir(parents=True)
    reranker_path.mkdir(parents=True)
    settings = Settings(
        EMBEDDING_MODEL_PATH=str(embedding_path),
        RERANKER_MODEL_PATH=str(reranker_path),
        DATA_DIR=str(tmp_path / "data"),
        UPLOAD_DIR=str(tmp_path / "data" / "uploads"),
        LOG_DIR=str(tmp_path / "data" / "logs"),
        METADATA_DB=str(tmp_path / "data" / "metadata.db"),
    )
    store = MetadataStore(tmp_path / "data" / "metadata.db")
    store.upsert_document(
        DocumentRecord(
            document_id="doc-1",
            filename="sample.pdf",
            source_path="data/uploads/sample.pdf",
            fingerprint="fp-1",
            status="indexed",
            page_count=1,
            ingested_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            metadata={},
        )
    )

    monkeypatch.setattr("app.api.routes.health.get_app_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.health.get_metadata_store", lambda: store)
    monkeypatch.setattr("app.api.routes.health.get_vector_store", lambda: _FakeVectorStore())
    monkeypatch.setattr("app.api.routes.health.get_bm25_store", lambda: _FakeBM25())
    monkeypatch.setattr("app.api.routes.health.get_primary_llm", lambda: _FakeLLM())
    monkeypatch.setattr("app.api.routes.health.get_fallback_llm", lambda: None)
    monkeypatch.setattr("app.api.routes.health.get_reranker", lambda: _FakeReranker())
    monkeypatch.setattr("app.api.routes.health.get_embedding_provider", lambda: _FakeEmbeddingProvider())
    monkeypatch.setattr("app.api.routes.health.get_redis_service", lambda: _FakeRedis())

    app = FastAPI()
    app.include_router(health_router)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["embedding_status"]["status"] == "ok"
    assert payload["reranker_status"]["status"] == "ok"
    assert payload["embedding_model_path"] == str(embedding_path)
    assert payload["reranker_model_path"] == str(reranker_path)

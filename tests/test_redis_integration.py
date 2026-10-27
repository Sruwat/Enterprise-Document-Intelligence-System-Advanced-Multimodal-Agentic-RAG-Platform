from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.rate_limit import InMemoryRateLimitMiddleware
from app.api.routes.ingest import _job_with_redis_progress, _mirror_job_progress
from app.core.config import Settings
from app.core.schemas import IngestionJobRecord
from app.services.readiness import LaunchReadinessService


class _FakeRedis:
    def __init__(self, status="ok"):
        self._status = status
        self.progress = {}

    def status(self):
        return {"status": self._status, "enabled": True, "url": "redis://test"}

    def set_ingestion_progress(self, job_id, payload, ttl_seconds=86400):
        self.progress[job_id] = payload

    def get_ingestion_progress(self, job_id):
        return self.progress.get(job_id)


class _Store:
    db_path = "metadata.db"

    def chunk_count(self):
        return 0

    def list_workspaces(self):
        return []


class _VectorStore:
    def is_available(self):
        return True

    def get_active_location(self):
        return "http://qdrant:6333"

    def count(self):
        return 0

    def verify_collection(self, vector_size=1024):
        return {"ok": True, "vector_size": vector_size}


class _Embedding:
    def status(self):
        return {"status": "ok", "dimension": 1024}


class _Reranker:
    def status(self):
        return {"status": "ok", "path": "models/bge-reranker-v2-m3"}


class _LLM:
    provider_name = "groq"
    model_name = "llama"


def test_ingestion_progress_round_trips_through_redis_overlay():
    redis = _FakeRedis()
    job = IngestionJobRecord(
        job_id="job-1",
        workspace_id="default",
        filename="source.pdf",
        status="embedding",
        progress=60,
        message="Embedding chunks.",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    _mirror_job_progress(redis, job)
    updated = _job_with_redis_progress(job.model_copy(update={"status": "uploaded", "progress": 0}), redis)

    assert updated.status == "embedding"
    assert updated.progress == 60
    assert updated.message == "Embedding chunks."


def test_production_readiness_blocks_when_redis_unavailable(tmp_path):
    settings = Settings(
        APP_ENV="production",
        ENABLE_REDIS=True,
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        GROQ_API_KEY="key",
        REQUIRE_AUTH=True,
        EMAIL_PROVIDER="smtp",
    )

    report = LaunchReadinessService(settings, _Store(), _VectorStore(), _Embedding(), _Reranker(), _LLM(), redis_service=_FakeRedis("error")).report()

    assert report["status"] == "blocked"
    assert any(check["name"] == "redis_runtime" and check["status"] == "blocker" for check in report["checks"])


def test_redis_rate_limit_backend_fails_closed_in_production(monkeypatch):
    settings = Settings(APP_ENV="production", ENABLE_REDIS=True, RATE_LIMIT_BACKEND="redis")
    monkeypatch.setattr("app.api.rate_limit.get_settings", lambda: settings)

    class _UnavailableRedis:
        def __init__(self, *_args, **_kwargs):
            pass

        def status(self):
            return {"status": "error", "detail": "down"}

        def rate_limit(self, *_args, **_kwargs):
            return True, 1

    monkeypatch.setattr("app.api.rate_limit.RedisService", _UnavailableRedis)
    app = FastAPI()
    app.add_middleware(InMemoryRateLimitMiddleware, enabled=True, requests=10, window_seconds=60)

    @app.get("/auth/probe")
    def probe():
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/auth/probe")

    assert response.status_code == 503

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.db.repositories.postgres_metadata import PostgresMetadataRepository
from app.services.cache import QueryCache
from app.services.evaluation.metrics import EvaluationService
from app.services.huggingface import HuggingFaceProviderRegistry
from app.services.readiness import LaunchReadinessService
from app.storage.metadata_store import MetadataStore


class _Embedding:
    def status(self):
        return {"status": "ok", "dimension": 1024}


class _Reranker:
    def status(self):
        return {"status": "ok", "path": "models/bge-reranker-v2-m3"}


class _LLM:
    provider_name = "groq"
    model_name = "llama-3.3-70b-versatile"


class _VectorStore:
    def is_available(self):
        return True

    def get_active_location(self):
        return "http://qdrant:6333"

    def count(self):
        return 0

    def verify_collection(self, vector_size=1024):
        return {
            "ok": True,
            "vector_size": vector_size,
            "payload_indexes": {"tenant_id": "keyword", "workspace_id": "keyword", "document_id": "keyword", "page_number": "integer", "content_type": "keyword", "objective_profile": "keyword"},
        }

    def verify_server_side_filters(self, vector_size=1024):
        return {"ok": True, "server_side": True, "vector_size": vector_size}


class _Redis:
    enabled = True

    def __init__(self):
        self.values = {}

    def get_json(self, key):
        return self.values.get(key)

    def set_json(self, key, value, ttl_seconds=None):
        self.values[key] = value

    def delete_prefix(self, prefix):
        keys = [key for key in self.values if key.startswith(prefix)]
        for key in keys:
            del self.values[key]
        return len(keys)


def _settings(tmp_path: Path, **overrides):
    model_path = tmp_path / "models" / "bge-m3"
    reranker_path = tmp_path / "models" / "bge-reranker-v2-m3"
    model_path.mkdir(parents=True)
    reranker_path.mkdir(parents=True)
    base = {
        "EMBEDDING_MODEL": "BAAI/bge-m3",
        "EMBEDDING_MODEL_PATH": str(model_path),
        "RERANKER_MODEL": "BAAI/bge-reranker-v2-m3",
        "RERANKER_MODEL_PATH": str(reranker_path),
        "QDRANT_COLLECTION": "aiwana_chunks_v2",
        "GROQ_API_KEY": "key",
        "DATA_DIR": str(tmp_path),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "LOG_DIR": str(tmp_path / "logs"),
        "METADATA_DB": str(tmp_path / "metadata.db"),
        "BACKUP_DIR": str(tmp_path / "backups"),
    }
    base.update(overrides)
    return Settings(**base)


def test_postgres_repository_runtime_status_reports_required_tables(tmp_path):
    repo = PostgresMetadataRepository(f"sqlite:///{tmp_path / 'metadata.db'}")

    status = repo.runtime_status()

    assert status["select_1"] is True
    assert status["status"] == "ok"
    assert "users" in status["required_tables"]
    assert status["missing_tables"] == []


def test_query_cache_keys_are_tenant_scoped_and_invalidated_by_workspace():
    redis = _Redis()
    cache = QueryCache(redis, ttl_seconds=60)
    key_a = cache.retrieval_key(
        tenant_id="tenant-a",
        workspace_id="workspace",
        question="What is risk?",
        document_ids=[],
        route="factual",
        objective_profile="enterprise",
        analysis_mode="quick",
        top_k=5,
        embedding_model="bge",
        reranker_model="rerank",
        index_version="1",
    )
    key_b = key_a.replace("tenant-a", "tenant-b")
    cache.set(key_a, {"candidates": [1]})
    cache.set(key_b, {"candidates": [2]})

    assert cache.get(key_a)["candidates"] == [1]
    assert cache.invalidate_workspace(tenant_id="tenant-a", workspace_id="workspace") == 1
    assert cache.get(key_a) is None
    assert cache.get(key_b)["candidates"] == [2]


def test_production_readiness_blocks_missing_postgres_runtime_probe(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = _settings(tmp_path, APP_ENV="production", DATABASE_BACKEND="postgres")

    report = LaunchReadinessService(settings, store, _VectorStore(), _Embedding(), _Reranker(), _LLM()).report()

    assert report["status"] == "blocked"
    assert any(check["name"] == "postgres_runtime" and check["status"] == "blocker" for check in report["checks"])


def test_graph_lift_eval_persists_and_readiness_can_pass_gate(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    service = EvaluationService(None, store)
    dataset = tmp_path / "graph.json"
    dataset.write_text('[{"query":"q","vector_only_score":0.4,"graph_enabled_score":0.7}]', encoding="utf-8")
    summary = service.run_graph_lift_evaluation(str(dataset))

    assert summary["metrics"]["graph_lift"]["lift"] == 0.3
    assert service.latest_graph_lift()["lift"] == 0.3


def test_huggingface_registry_reports_task_level_degraded_without_crashing(tmp_path):
    registry = HuggingFaceProviderRegistry(enabled=True, cache_dir=tmp_path, task_enables={"entity_extraction": True}, max_seconds=1)

    result = registry.provider_for("entity_extraction").run("Acme signed with NovaTech.")
    status = registry.status()

    assert result["status"] in {"ready", "fallback"}
    assert status["providers"]["entity_extraction"]["status"] in {"configured", "degraded", "ready"}

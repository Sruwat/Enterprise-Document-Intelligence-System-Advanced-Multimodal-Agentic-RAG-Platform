from app.core.config import Settings
from app.core.schemas import ChunkRecord
from app.services.backup import BackupService
from app.services.readiness import LaunchReadinessService
from app.storage.metadata_store import MetadataStore


class _Embedding:
    def __init__(self, dimension=1024, status="ok"):
        self.dimension = dimension
        self._status = status

    def status(self):
        return {"status": self._status, "dimension": self.dimension}


class _Reranker:
    def status(self):
        return {"status": "ok", "path": "models/bge-reranker-v2-m3"}


class _LLM:
    provider_name = "groq"
    model_name = "llama-3.3-70b-versatile"


class _FallbackLLM:
    provider_name = "grounded_fallback"
    model_name = "extractive-local-v2"


class _VectorStore:
    def __init__(self, location="http://qdrant:6333", available=True):
        self.location = location
        self.available = available

    def is_available(self):
        return self.available

    def get_active_location(self):
        return self.location

    def count(self):
        return 10

    def verify_collection(self, vector_size=1024):
        return {
            "ok": True,
            "points_count": 10,
            "named_vectors": ["text_dense", "visual_dense", "table_dense"],
            "sparse_vectors": [],
            "payload_indexes": {
                "tenant_id": "keyword",
                "workspace_id": "keyword",
                "document_id": "keyword",
                "page_number": "integer",
                "content_type": "keyword",
                "objective_profile": "keyword",
            },
            "vector_size": vector_size,
        }

    def verify_server_side_filters(self, vector_size=1024):
        return {"ok": True, "server_side": True, "vector_size": vector_size, "result_count": 0}


def test_launch_readiness_blocks_old_embedding_profile(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    old_model = tmp_path / "models" / "bge-small-en-v1.5"
    old_model.mkdir(parents=True)
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-small-en-v1.5",
        EMBEDDING_MODEL_PATH=str(old_model),
        QDRANT_COLLECTION="rag_chunks",
        GROQ_API_KEY="key",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )

    report = LaunchReadinessService(settings, store, _VectorStore(), _Embedding(384), _Reranker(), _LLM()).report()

    assert report["status"] == "blocked"
    assert any(check["name"] == "model_profile" and check["status"] == "blocker" for check in report["checks"])


def test_launch_readiness_passes_launch_profile(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    bge_m3 = tmp_path / "models" / "bge-m3"
    bge_m3.mkdir(parents=True)
    (tmp_path / "eval_dataset_novatech.json").write_text("[]", encoding="utf-8")
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH=str(bge_m3),
        RERANKER_MODEL="BAAI/bge-reranker-v2-m3",
        RERANKER_MODEL_PATH=str(tmp_path / "models" / "bge-reranker-v2-m3"),
        QDRANT_COLLECTION="aiwana_chunks_v2",
        GROQ_API_KEY="key",
        ENABLE_PERSISTENT_MEMORY=True,
        ENABLE_MULTIMODAL=True,
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )
    BackupService(settings, store, _VectorStore()).create_backup(tmp_path / "backups" / "smoke")

    report = LaunchReadinessService(settings, store, _VectorStore(), _Embedding(1024), _Reranker(), _LLM()).report()

    assert report["status"] == "ready"
    assert report["blocker_count"] == 0
    assert any(check["name"] == "qdrant_schema" and check["status"] == "ok" for check in report["checks"])


def test_launch_readiness_blocks_missing_groq(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    bge_m3 = tmp_path / "models" / "bge-m3"
    bge_m3.mkdir(parents=True)
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH=str(bge_m3),
        QDRANT_COLLECTION="aiwana_chunks_v2",
        GROQ_API_KEY="",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )

    report = LaunchReadinessService(settings, store, _VectorStore(), _Embedding(1024), _Reranker(), _FallbackLLM()).report()

    assert report["status"] == "blocked"
    assert any(check["name"] == "llm_provider" and check["status"] == "blocker" for check in report["checks"])


def test_launch_readiness_blocks_production_without_auth(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    bge_m3 = tmp_path / "models" / "bge-m3"
    bge_m3.mkdir(parents=True)
    (tmp_path / "eval_dataset_novatech.json").write_text("[]", encoding="utf-8")
    settings = Settings(
        APP_ENV="production",
        REQUIRE_AUTH=False,
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH=str(bge_m3),
        QDRANT_COLLECTION="aiwana_chunks_v2",
        GROQ_API_KEY="key",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )

    report = LaunchReadinessService(settings, store, _VectorStore(), _Embedding(1024), _Reranker(), _LLM()).report()

    assert report["status"] == "blocked"
    assert any(check["name"] == "security_profile" and check["status"] == "blocker" for check in report["checks"])


def test_launch_readiness_blocks_vector_metadata_mismatch(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    store.insert_chunks([
        ChunkRecord(chunk_id="chunk-1", document_id="doc-1", workspace_id="default", filename="doc.pdf", page_number=1, text="one", token_count=1),
        ChunkRecord(chunk_id="chunk-2", document_id="doc-1", workspace_id="default", filename="doc.pdf", page_number=1, text="two", token_count=1),
    ])
    bge_m3 = tmp_path / "models" / "bge-m3"
    bge_m3.mkdir(parents=True)
    (tmp_path / "eval_dataset_novatech.json").write_text("[]", encoding="utf-8")
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH=str(bge_m3),
        QDRANT_COLLECTION="aiwana_chunks_v2",
        GROQ_API_KEY="key",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )

    report = LaunchReadinessService(settings, store, _VectorStore(), _Embedding(1024), _Reranker(), _LLM()).report()

    assert report["status"] == "blocked"
    assert any(check["name"] == "vector_reconciliation" and check["status"] == "blocker" for check in report["checks"])


def test_launch_readiness_warns_without_backup_marker(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    bge_m3 = tmp_path / "models" / "bge-m3"
    bge_m3.mkdir(parents=True)
    (tmp_path / "eval_dataset_novatech.json").write_text("[]", encoding="utf-8")
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH=str(bge_m3),
        QDRANT_COLLECTION="aiwana_chunks_v2",
        GROQ_API_KEY="key",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        BACKUP_DIR=str(tmp_path / "backups"),
    )

    report = LaunchReadinessService(settings, store, _VectorStore(), _Embedding(1024), _Reranker(), _LLM()).report()

    assert report["status"] == "warning"
    assert any(check["name"] == "backup_restore" and check["status"] == "warning" for check in report["checks"])

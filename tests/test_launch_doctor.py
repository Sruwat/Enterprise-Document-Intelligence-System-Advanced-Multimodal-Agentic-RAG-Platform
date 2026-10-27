import subprocess

from app.core.config import Settings
from app.core.schemas import DocumentRecord
from app.services.launch_doctor import LaunchDoctor


class _Store:
    def __init__(self, documents=None):
        self.documents = documents or []

    def list_documents(self):
        return self.documents


class _VectorStore:
    collection_name = "aiwana_chunks_v2"

    def is_available(self):
        return True

    def get_active_location(self):
        return "http://qdrant:6333"

    def count(self):
        return 0

    def verify_collection(self, vector_size=1024):
        return {
            "ok": True,
            "points_count": 0,
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


def test_launch_doctor_blocks_legacy_profile(tmp_path):
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-small-en-v1.5",
        EMBEDDING_MODEL_PATH=str(tmp_path / "models" / "bge-small-en-v1.5"),
        QDRANT_COLLECTION="rag_chunks",
        GROQ_API_KEY="",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        BACKUP_DIR=str(tmp_path / "backups"),
    )

    report = LaunchDoctor(settings, _Store()).report()

    assert report["status"] == "blocked"
    assert report["summary"] == f"Launch blocked by {report['blocker_count']} critical readiness issue(s)."
    assert any(check["name"] == "env_profile" and check["status"] == "blocker" for check in report["checks"])
    assert "python tools/download_aiwana_models.py" in report["next_commands"]


def test_launch_doctor_capability_gates_block_disabled_production_services(tmp_path):
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH="models/bge-m3",
        RERANKER_MODEL="BAAI/bge-reranker-v2-m3",
        RERANKER_MODEL_PATH="models/bge-reranker-v2-m3",
        QDRANT_COLLECTION="aiwana_chunks_v2",
        GROQ_API_KEY="x",
        ENABLE_REAL_ORCHESTRATOR=False,
        ENABLE_GRAPH_MEMORY=False,
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        BACKUP_DIR=str(tmp_path / "backups"),
    )

    check = LaunchDoctor(settings, _Store(), _VectorStore(), include_production=True)._check_capability_gates()

    assert check["status"] == "blocker"
    assert "ENABLE_REAL_ORCHESTRATOR=false" in check["details"]["blockers"]
    assert "ENABLE_GRAPH_MEMORY=false" in check["details"]["blockers"]


def test_launch_doctor_ready_when_profile_assets_and_documents_exist(tmp_path):
    bge_m3 = tmp_path / "models" / "bge-m3"
    reranker = tmp_path / "models" / "bge-reranker-v2-m3"
    bge_m3.mkdir(parents=True)
    reranker.mkdir(parents=True)
    (bge_m3 / "pytorch_model.bin").write_bytes(b"weights")
    (reranker / "model.safetensors").write_bytes(b"weights")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF fake")
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH=str(bge_m3),
        RERANKER_MODEL="BAAI/bge-reranker-v2-m3",
        RERANKER_MODEL_PATH=str(reranker),
        QDRANT_COLLECTION="aiwana_chunks_v2",
        QDRANT_LOCAL_FALLBACK_URL="disabled",
        GROQ_API_KEY="key",
        ENABLE_NAMED_VECTORS=True,
        ENABLE_PERSISTENT_MEMORY=True,
        ENABLE_GRAPH_MEMORY=False,
        ENABLE_REDIS=False,
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )
    backup_dir = tmp_path / "backups" / "smoke"
    backup_dir.mkdir(parents=True)
    (tmp_path / "backups" / "latest_backup.json").write_text(
        '{"backup_dir": "' + str(backup_dir).replace("\\", "\\\\") + '", "created_at": "2099-01-01T00:00:00"}',
        encoding="utf-8",
    )
    document = DocumentRecord(
        document_id="doc-1",
        workspace_id="default",
        filename="source.pdf",
        source_path=str(source),
        fingerprint="fingerprint",
        status="indexed",
        page_count=1,
        ingested_at=__import__("datetime").datetime.utcnow(),
        metadata={},
    )

    report = LaunchDoctor(settings, _Store([document]), _VectorStore()).report()

    assert report["status"] == "ready"
    assert report["summary"] == "Aiwana launch readiness checks passed."
    assert "python tools/migrate_aiwana_v2.py --reingest" in report["next_commands"]


def test_launch_doctor_warns_when_backup_marker_missing(tmp_path):
    bge_m3 = tmp_path / "models" / "bge-m3"
    reranker = tmp_path / "models" / "bge-reranker-v2-m3"
    bge_m3.mkdir(parents=True)
    reranker.mkdir(parents=True)
    (bge_m3 / "pytorch_model.bin").write_bytes(b"weights")
    (reranker / "model.safetensors").write_bytes(b"weights")
    settings = Settings(
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH=str(bge_m3),
        RERANKER_MODEL="BAAI/bge-reranker-v2-m3",
        RERANKER_MODEL_PATH=str(reranker),
        QDRANT_COLLECTION="aiwana_chunks_v2",
        QDRANT_LOCAL_FALLBACK_URL="disabled",
        GROQ_API_KEY="key",
        ENABLE_REDIS=False,
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        BACKUP_DIR=str(tmp_path / "backups"),
    )

    report = LaunchDoctor(settings, _Store(), _VectorStore()).report()

    assert report["status"] == "warning"
    assert report["summary"] == "Launch has 2 warning(s) to resolve or accept."
    assert any(check["name"] == "backup_restore" and check["status"] == "warning" for check in report["checks"])


def test_frontend_build_check_passes_with_project_root(monkeypatch, tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    settings = Settings(DATA_DIR=str(tmp_path), UPLOAD_DIR=str(tmp_path / "uploads"), LOG_DIR=str(tmp_path / "logs"), METADATA_DB=str(tmp_path / "metadata.db"))

    def fake_run(command, cwd, check, capture_output, text, encoding, errors, timeout):
        assert command[-2:] == ["run", "build"]
        assert cwd == frontend
        return subprocess.CompletedProcess(command, 0, stdout="Compiled successfully", stderr="")

    monkeypatch.setattr("app.services.launch_doctor.subprocess.run", fake_run)

    check = LaunchDoctor(settings, project_root=tmp_path, include_frontend=True)._check_frontend_build()

    assert check["status"] == "ok"
    assert check["details"]["retried_after_clean"] is False


def test_frontend_build_check_cleans_stale_next_document_cache(monkeypatch, tmp_path):
    frontend = tmp_path / "frontend"
    next_dir = frontend / ".next"
    next_dir.mkdir(parents=True)
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    (next_dir / "stale").write_text("old build", encoding="utf-8")
    settings = Settings(DATA_DIR=str(tmp_path), UPLOAD_DIR=str(tmp_path / "uploads"), LOG_DIR=str(tmp_path / "logs"), METADATA_DB=str(tmp_path / "metadata.db"))
    calls = {"count": 0}

    def fake_run(command, cwd, check, capture_output, text, encoding, errors, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="PageNotFoundError: Cannot find module for page: /_document")
        return subprocess.CompletedProcess(command, 0, stdout="Compiled successfully", stderr="")

    monkeypatch.setattr("app.services.launch_doctor.subprocess.run", fake_run)

    check = LaunchDoctor(settings, project_root=tmp_path, include_frontend=True)._check_frontend_build()

    assert check["status"] == "ok"
    assert check["details"]["retried_after_clean"] is True
    assert calls["count"] == 2
    assert not next_dir.exists()


def test_launch_doctor_blocks_production_when_redis_unavailable(monkeypatch, tmp_path):
    settings = Settings(
        APP_ENV="production",
        ENABLE_REDIS=True,
        DATABASE_BACKEND="postgres",
        EMBEDDING_MODEL="BAAI/bge-m3",
        EMBEDDING_MODEL_PATH=str(tmp_path / "models" / "bge-m3"),
        RERANKER_MODEL="BAAI/bge-reranker-v2-m3",
        RERANKER_MODEL_PATH=str(tmp_path / "models" / "bge-reranker-v2-m3"),
        QDRANT_COLLECTION="aiwana_chunks_v2",
        GROQ_API_KEY="key",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )

    class _Redis:
        def __init__(self, *_args, **_kwargs):
            pass

        def status(self):
            return {"status": "error", "detail": "down"}

    monkeypatch.setattr("app.services.launch_doctor.RedisService", _Redis)

    check = LaunchDoctor(settings, _Store(), include_production=True)._check_redis_profile()

    assert check["status"] == "blocker"
    assert check["name"] == "redis_profile"


def test_launch_doctor_warns_when_graph_enabled_without_postgres(tmp_path):
    settings = Settings(
        ENABLE_GRAPH_MEMORY=True,
        DATABASE_BACKEND="sqlite",
        GRAPH_BACKEND="postgres",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )

    check = LaunchDoctor(settings, _Store())._check_graph_profile()

    assert check["status"] == "warning"
    assert "DATABASE_BACKEND=postgres" in check["message"]


def test_launch_doctor_include_evals_blocks_weak_seeded_run(tmp_path):
    settings = Settings(
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )
    (tmp_path / "eval_dataset_aiwana_launch.json").write_text('[{"query":"q","category":"citation"}]', encoding="utf-8")

    class _EvalService:
        def launch_gates(self, **_kwargs):
            return {"status": "blocked", "checks": [{"name": "seeded_benchmark_pass_rate", "status": "blocker"}]}

    check = LaunchDoctor(settings, _Store(), _VectorStore(), _EvalService(), include_evals=True)._check_evaluation_gates()

    assert check["status"] == "blocker"
    assert check["name"] == "evaluation_gates"


def test_launch_doctor_include_evals_accepts_ready_seeded_run(tmp_path):
    settings = Settings(
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )
    (tmp_path / "eval_dataset_aiwana_launch.json").write_text('[{"query":"q","category":"citation"}]', encoding="utf-8")

    class _EvalService:
        def launch_gates(self, **_kwargs):
            return {"status": "ready", "checks": []}

    check = LaunchDoctor(settings, _Store(), _VectorStore(), _EvalService(), include_evals=True)._check_evaluation_gates()

    assert check["status"] == "ok"

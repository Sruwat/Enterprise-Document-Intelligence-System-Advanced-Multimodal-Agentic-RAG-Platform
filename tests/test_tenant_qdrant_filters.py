from app.core.schemas import ChunkRecord
from app.services.backup import BackupService
from app.services.retrieval.dense import DenseRetriever
from app.storage.metadata_store import MetadataStore
from app.storage.qdrant import QdrantPayloadFilter, QdrantVectorStore
from app.core.config import Settings


def test_qdrant_fallback_filters_prevent_cross_tenant_results():
    store = QdrantVectorStore(":memory:", "tenant_filter_test")
    store.client = None
    store.upsert(
        ["a", "b"],
        [[1.0, 0.0], [1.0, 0.0]],
        [
            {"tenant_id": "tenant-a", "workspace_id": "workspace-a", "document_id": "doc-a", "objective_profile": "legal"},
            {"tenant_id": "tenant-b", "workspace_id": "workspace-b", "document_id": "doc-b", "objective_profile": "legal"},
        ],
    )

    results = store.query([1.0, 0.0], filters=QdrantPayloadFilter(tenant_id="tenant-a", workspace_id="workspace-a"))

    assert [result["id"] for result in results] == ["a"]
    assert store.verify_server_side_filters(2)["ok"] is True


def test_dense_retriever_passes_tenant_document_and_objective_filters_to_qdrant(tmp_path):
    class _Embedder:
        def embed_query(self, _question):
            return [1.0, 0.0]

    class _VectorStore:
        def __init__(self):
            self.filters = None

        def query(self, _vector, limit=5, vector_name=None, filters=None):
            self.filters = filters
            return [{"id": "chunk-1", "score": 0.9}]

        def query_sparse(self, *_args, **_kwargs):
            return []

    metadata = MetadataStore(tmp_path / "metadata.db")
    metadata.insert_chunks(
        [
            ChunkRecord(
                chunk_id="chunk-1",
                document_id="doc-1",
                workspace_id="workspace-a",
                filename="doc.pdf",
                page_number=1,
                text="Termination requires notice.",
                token_count=4,
            )
        ]
    )
    vector_store = _VectorStore()
    retriever = DenseRetriever(vector_store, _Embedder(), metadata)

    chunks = retriever.retrieve(
        "termination notice",
        workspace_id="workspace-a",
        document_ids=["doc-1"],
        tenant_id="tenant-a",
        objective_profile="legal",
    )

    assert [chunk.chunk_id for chunk in chunks] == ["chunk-1"]
    assert vector_store.filters == {
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "document_id": ["doc-1"],
        "objective_profile": "legal",
    }


def test_qdrant_snapshot_manifest_validates_missing_snapshot(tmp_path):
    class _VectorStore:
        collection_name = "aiwana_chunks_v2"

        def collection_report(self):
            return {"collection": self.collection_name, "points_count": 0}

        def list_snapshots(self):
            return {"status": "ok", "collection": self.collection_name, "snapshots": [{"name": "snapshot-a"}]}

    settings = Settings(
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        BACKUP_DIR=str(tmp_path / "backups"),
        GROQ_API_KEY="key",
    )
    metadata = MetadataStore(settings.metadata_db)
    backup_dir = tmp_path / "backups" / "smoke"
    service = BackupService(settings, metadata, _VectorStore())
    service.create_backup(backup_dir)
    manifest_path = backup_dir / "qdrant_manifest.json"
    payload = manifest_path.read_text(encoding="utf-8").replace("snapshot-a", "missing-snapshot")
    manifest_path.write_text(payload, encoding="utf-8")

    validation = service.validate_restore(backup_dir)

    assert validation["status"] == "blocked"
    assert any("missing-snapshot" in error for error in validation["errors"])

from datetime import datetime

from app.core.config import Settings
from app.core.schemas import ChunkRecord, DeletionRequestRecord, DocumentRecord
from app.services.data_vault import DataVaultService, DocumentPurgeService
from app.services.retention import RetentionPolicyEngine
from app.services.tenant_data_plane import TenantDataPlaneResolver
from app.storage.metadata_store import MetadataStore


def test_lineage_is_built_from_real_document_dependencies(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(DATA_DIR=str(tmp_path), UPLOAD_DIR=str(tmp_path / "uploads"), METADATA_DB=str(tmp_path / "metadata.db"))
    owner = store.create_user("lineage@example.com", tenant_id="tenant-lineage")
    workspace = store.create_workspace("Lineage", owner_id=owner.user_id, tenant_id=owner.tenant_id, private_mode=True, external_ai_allowed=False)
    source = tmp_path / "uploads" / "agreement.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"agreement")
    document = DocumentRecord(document_id="doc-lineage", workspace_id=workspace.workspace_id, filename="agreement.pdf", source_path=str(source), fingerprint="fp", status="indexed", page_count=3, ingested_at=datetime.utcnow(), metadata={"processing_metadata": {"ocr_provider": "local_paddle", "embedding_provider": "private_bge", "index_version": 2}, "page_asset_refs": [{"ocr_attempted": True}]})
    store.upsert_document(document)
    store.insert_chunks([ChunkRecord(chunk_id="c1", document_id=document.document_id, workspace_id=workspace.workspace_id, filename=document.filename, page_number=1, text="termination")])

    class Vector:
        def count(self, filters): return 1

    class Graph:
        def document_counts(self, **kwargs): return {"entities": 2, "relationships": 1}

    lineage = DataVaultService(metadata_store=store, vector_store=Vector(), graph_repository=Graph(), settings=settings).lineage(document=document, tenant_id=workspace.tenant_id)
    assert [stage.stage for stage in lineage.stages] == ["original", "extraction", "ocr", "chunks", "embeddings", "vector_db", "graph", "rag"]
    assert next(stage for stage in lineage.stages if stage.stage == "graph").details["relationships"] == 1


def test_retention_and_data_plane_are_server_side_contracts():
    engine = RetentionPolicyEngine()
    expiry = engine.expiry_for(mode="temporary_analysis", retention="1h", policy=engine.resolve(workspace=None, document=None), now=datetime(2026, 1, 1))
    assert expiry.isoformat() == "2026-01-01T01:00:00"
    resolver = TenantDataPlaneResolver(default_mode="shared", registry={"tenant-a": {"mode": "dedicated", "postgres_secret_ref": "sm://tenant-a/db"}})
    assert resolver.resolve("tenant-a").mode == "dedicated"
    assert resolver.resolve("tenant-a").postgres_secret_ref == "sm://tenant-a/db"
    assert resolver.resolve("tenant-b").mode == "shared"


def test_deletion_request_is_tenant_scoped_and_persisted(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    record = DeletionRequestRecord(request_id="request-1", tenant_id="tenant-a", workspace_id="workspace-a", document_id="doc-a", requested_by="user-a", reason="temporary analysis complete", created_at=datetime.utcnow())
    store.create_deletion_request(record)
    assert store.get_deletion_request("request-1", "workspace-b") is None
    found = store.get_deletion_request("request-1", "workspace-a")
    assert found is not None and found.status == "pending"
    updated = store.update_deletion_request("request-1", status="approved", approved_by="admin-a")
    assert updated is not None and updated.approved_by == "admin-a"

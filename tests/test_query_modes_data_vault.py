from __future__ import annotations

from datetime import datetime

from app.api.auth_context import hash_token
from app.core.config import Settings
from app.core.schemas import ChunkRecord, DocumentRecord, QueryRequest
from app.services.data_vault import DataVaultService, DocumentPurgeService
from app.services.industry_packs import list_industry_packs
from app.services.reranker.cross_encoder import CrossEncoderReranker
from app.services.retrieval.query_modes import QueryModeResolver
from app.storage.metadata_store import MetadataStore


def test_query_mode_resolver_bounds_fast_balanced_and_deep():
    settings = Settings(
        FAST_RETRIEVAL_K=18,
        FAST_CONTEXT_K=4,
        BALANCED_RETRIEVAL_K=28,
        BALANCED_RERANK_K=14,
        DEEP_RETRIEVAL_K=80,
        DEEP_RERANK_K=60,
        RERANK_MAX_CANDIDATES=24,
        DEEP_CONTEXT_K=12,
        ENABLE_RERANKER=True,
        RERANKER_REQUIRED=True,
    )
    resolver = QueryModeResolver()

    fast = resolver.resolve(QueryRequest(question="What is the due date?", query_mode="fast"), settings)
    balanced = resolver.resolve(QueryRequest(question="What is the due date?", query_mode="balanced"), settings)
    deep = resolver.resolve(QueryRequest(question="Compare contract risks across all vendors", query_mode="deep", mode="multistep"), settings)
    auto = resolver.resolve(QueryRequest(question="Compare obligations and conflicts across these contracts", query_mode="auto"), settings)

    assert fast.use_reranker is False
    assert fast.use_graph is False
    assert fast.candidate_pool == 18
    assert balanced.use_reranker is True
    assert balanced.rerank_k == 14
    assert deep.rerank_k == 24
    assert deep.use_multistep is True
    assert deep.reranker_required is True
    assert auto.mode == "deep"


def test_industry_pack_catalog_exposes_private_document_use_cases():
    packs = list_industry_packs()
    pack_ids = {pack["pack_id"] for pack in packs}

    assert {"legal-contracts", "finance-diligence", "insurance-underwriting", "manufacturing-quality"}.issubset(pack_ids)
    assert all(pack["prompt_starters"] for pack in packs)
    assert any("private" in pack["data_boundary"] or "restricted" in pack["data_boundary"] for pack in packs)


def test_cross_encoder_reranker_limits_candidates_and_records_status(tmp_path):
    class FakeModel:
        def __init__(self) -> None:
            self.seen_pairs = []
            self.seen_batch_size = None

        def predict(self, pairs, batch_size=None):
            self.seen_pairs = pairs
            self.seen_batch_size = batch_size
            return [float(index) for index, _ in enumerate(pairs)]

    model = FakeModel()
    reranker = CrossEncoderReranker(tmp_path, max_candidates=5, batch_size=3, timeout_seconds=30)
    reranker._load = lambda: model
    chunks = [
        ChunkRecord(chunk_id=f"c-{index}", document_id="doc", filename="doc.pdf", page_number=1, text=f"chunk {index}")
        for index in range(12)
    ]

    ranked = reranker.rerank("question", chunks, top_n=10)

    assert len(model.seen_pairs) == 5
    assert model.seen_batch_size == 3
    assert [chunk.chunk_id for chunk in ranked] == ["c-4", "c-3", "c-2", "c-1", "c-0"]
    assert reranker.last_status["candidate_count"] == 5
    assert reranker.last_status["status"] == "ok"


def test_data_vault_overview_reports_workspace_footprint(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(DATA_DIR=str(tmp_path), UPLOAD_DIR=str(tmp_path / "uploads"), METADATA_DB=str(tmp_path / "metadata.db"))
    owner = store.create_user("owner@example.com", tenant_id="tenant-a")
    workspace = store.create_workspace("Vault", owner_id=owner.user_id, tenant_id=owner.tenant_id, private_mode=True, external_ai_allowed=False)
    source = tmp_path / "uploads" / "vault.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"private document")
    document = DocumentRecord(
        document_id="doc-1",
        workspace_id=workspace.workspace_id,
        filename="vault.pdf",
        source_path=str(source),
        fingerprint="fp",
        status="indexed",
        page_count=2,
        ingested_at=datetime.utcnow(),
        metadata={
            "document_mode": "temporary_analysis",
            "classification": "regulated",
            "external_processing_allowed": False,
            "page_asset_refs": [{"ocr_attempted": True}, {"ocr_available": True}],
        },
    )
    store.upsert_document(document)
    store.insert_chunks(
        [
            ChunkRecord(chunk_id="c-1", document_id="doc-1", workspace_id=workspace.workspace_id, filename="vault.pdf", page_number=1, text="alpha"),
            ChunkRecord(chunk_id="c-2", document_id="doc-1", workspace_id=workspace.workspace_id, filename="vault.pdf", page_number=2, text="beta"),
        ]
    )

    class VectorStore:
        def __init__(self) -> None:
            self.filters = None

        def count(self, filters=None):
            self.filters = filters
            return 2

    class GraphRepository:
        def document_counts(self, **kwargs):
            return {"entities": 3, "relationships": 2}

    vector_store = VectorStore()
    overview = DataVaultService(metadata_store=store, vector_store=vector_store, graph_repository=GraphRepository(), settings=settings).overview(
        workspace_id=workspace.workspace_id,
        tenant_id=workspace.tenant_id,
    )

    assert overview.documents == 1
    assert overview.indexed_chunks == 2
    assert overview.vector_embeddings == 2
    assert overview.ocr_pages == 2
    assert overview.graph_entities == 3
    assert overview.privacy_mode == "private"
    assert overview.documents_footprint[0].privacy_boundary["private_processing_required"] is True
    assert vector_store.filters == {"tenant_id": workspace.tenant_id, "workspace_id": workspace.workspace_id, "document_id": "doc-1"}


def test_document_purge_removes_indexes_and_records_receipt(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(DATA_DIR=str(tmp_path), UPLOAD_DIR=str(tmp_path / "uploads"), METADATA_DB=str(tmp_path / "metadata.db"))
    owner = store.create_user("owner@example.com", tenant_id="tenant-a")
    store.create_auth_session(hash_token("token"), owner.user_id, datetime.utcnow().replace(year=2099))
    workspace = store.create_workspace("Vault", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    source = tmp_path / "uploads" / "delete-me.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"delete me")
    document = DocumentRecord(
        document_id="doc-delete",
        workspace_id=workspace.workspace_id,
        filename="delete-me.pdf",
        source_path=str(source),
        fingerprint="fp-delete",
        status="indexed",
        page_count=1,
        ingested_at=datetime.utcnow(),
        metadata={},
    )
    store.upsert_document(document)
    store.insert_chunks([ChunkRecord(chunk_id="chunk-delete", document_id=document.document_id, workspace_id=workspace.workspace_id, filename=document.filename, page_number=1, text="text")])

    class VectorStore:
        deleted = None

        def delete(self, chunk_ids):
            self.deleted = chunk_ids

    class SparseStore:
        removed = None

        def remove_documents(self, chunk_ids):
            self.removed = chunk_ids

    class Cache:
        def invalidate_workspace(self, **kwargs):
            return 1

    class GraphRepository:
        def delete_document_graph(self, **kwargs):
            return {"entities_deleted": 1, "relationships_deleted": 1}

    vector_store = VectorStore()
    sparse_store = SparseStore()
    job = DocumentPurgeService(
        metadata_store=store,
        vector_store=vector_store,
        sparse_store=sparse_store,
        query_cache=Cache(),
        graph_repository=GraphRepository(),
        settings=settings,
    ).purge(document=document, tenant_id=workspace.tenant_id, user=owner, reason="test_purge")

    assert job.status == "completed"
    assert vector_store.deleted == ["chunk-delete"]
    assert sparse_store.removed == ["chunk-delete"]
    assert store.get_document(document.document_id, workspace_id=workspace.workspace_id) is None
    assert source.exists() is False
    assert store.list_purge_jobs(workspace.workspace_id)[0].receipt["stages"]["vectors"]["count"] == 1

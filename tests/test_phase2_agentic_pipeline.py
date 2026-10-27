from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_context import hash_token
from app.api.routes.query import router as query_router
from app.core.config import Settings
from app.core.dependencies import (
    get_agent_orchestrator,
    get_agentic_query_engine,
    get_app_settings,
    get_context_agent,
    get_dense_retriever,
    get_enterprise_agent,
    get_evidence_agent,
    get_eval_logger,
    get_fallback_llm,
    get_graph_repository,
    get_hybrid_retriever,
    get_legal_agent,
    get_metadata_store,
    get_multistep_engine,
    get_primary_llm,
    get_query_planner,
    get_reranker,
    get_retrieval_agent,
    get_redis_service,
    get_router,
    get_session_memory,
    get_study_agent,
    get_synthesis_agent,
)
from app.core.schemas import ChunkRecord, Citation, QueryResponse
from app.services.huggingface import HuggingFaceProviderRegistry
from app.services.retrieval.citation_verifier import CitationVerifier
from app.services.retrieval.graph_enricher import GraphEvidenceEnricher
from app.services.retrieval.query_rewriter import QueryRewriter
from app.storage.metadata_store import MetadataStore


class _DelegatingEngine:
    def __init__(self):
        self.called = False

    def run(self, *, request, services, user):
        self.called = True
        return QueryResponse(
            answer="Engine-owned response. [Source: doc.pdf p.1 chunk-1]",
            citations=[Citation(document_id="doc-1", filename="doc.pdf", page_number=1, chunk_id="chunk-1", snippet="Engine-owned response.")],
            confidence=0.9,
            abstained=False,
            route_used="factual",
            retrieved_chunks=[],
            latency_ms={"total": 1.0},
            agent_plan={"run_mode": "agentic"},
            tool_trace=[{"tool_name": "search_documents"}],
            verification={"grounding_status": "grounded"},
            grounding_status="grounded",
        )

    def stream(self, *, request, services, user):
        self.called = True
        yield 'event: completed\ndata: {"ok": true}\n\n'


def test_query_routes_delegate_to_agentic_engine(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(REQUIRE_AUTH=True, ENABLE_LOCAL_USER_FALLBACK=False, DATABASE_BACKEND="sqlite", METADATA_DB=str(tmp_path / "metadata.db"))
    owner = store.create_user("phase2@example.com", tenant_id="tenant-phase2")
    workspace = store.create_workspace("Phase 2", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    token = "phase2-token"
    store.create_auth_session(hash_token(token), owner.user_id, datetime.utcnow().replace(year=2099))
    engine = _DelegatingEngine()
    app = FastAPI()
    app.include_router(query_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_agentic_query_engine] = lambda: engine
    for dependency in (
        get_agent_orchestrator,
        get_router,
        get_dense_retriever,
        get_hybrid_retriever,
        get_reranker,
        get_query_planner,
        get_multistep_engine,
        get_session_memory,
        get_primary_llm,
        get_fallback_llm,
        get_graph_repository,
        get_eval_logger,
        get_redis_service,
        get_context_agent,
        get_retrieval_agent,
        get_evidence_agent,
        get_legal_agent,
        get_study_agent,
        get_enterprise_agent,
        get_synthesis_agent,
    ):
        app.dependency_overrides[dependency] = lambda: object()

    with TestClient(app) as client:
        response = client.post(
            "/chat/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"workspace_id": workspace.workspace_id, "question": "What is in the doc?"},
        )

    assert response.status_code == 200
    assert engine.called is True
    assert response.json()["agent_plan"]["run_mode"] == "agentic"


def test_rewrite_graph_and_citation_helpers_are_offline_safe():
    rewrites = QueryRewriter().expand("What does it say?", route_used="follow_up", objective_profile="legal")
    assert len(rewrites) >= 2
    assert any("clause obligation" in query for query in rewrites)

    class _Entity:
        workspace_id = "workspace-a"
        canonical_name = "NovaTech"
        entity_type = "Company"

    class _Relationship:
        relationship_type = "CREATES_OBLIGATION"

    class _Fact:
        source = _Entity()
        target = None
        relationship = _Relationship()
        evidence_anchor_id = "anchor-1"
        document_id = "doc-1"
        page_number = 3

    graph_chunks = GraphEvidenceEnricher().facts_to_chunks([_Fact()], workspace_id="workspace-a", limit=5)
    assert graph_chunks[0].metadata["content_type"] == "graph_fact"
    assert graph_chunks[0].combined_score == 0.99

    chunk = ChunkRecord(chunk_id="chunk-1", document_id="doc-1", filename="doc.pdf", page_number=3, text="NovaTech creates an obligation.")
    citation = Citation(document_id="doc-1", filename="doc.pdf", page_number=3, chunk_id="chunk-1", snippet="NovaTech creates an obligation.")
    verification = CitationVerifier().verify(answer="NovaTech creates an obligation. [Source: doc.pdf p.3 chunk-1]", citations=[citation], chunks=[chunk])
    assert verification["all_verified"] is True
    assert verification["claim_checks"][0]["status"] == "ok"


def test_huggingface_registry_task_adapters_degrade_safely(tmp_path):
    registry = HuggingFaceProviderRegistry(enabled=True, cache_dir=tmp_path)

    entities = registry.extract_entities("NovaTech signed the Alpha Agreement with River Labs.")
    evidence = registry.check_evidence(answer="NovaTech signed Alpha Agreement.", evidence=["NovaTech signed the Alpha Agreement."])
    reranked = registry.rerank("Alpha Agreement", ["unrelated text", "Alpha Agreement details"], top_n=1)

    assert "NovaTech" in entities["entities"]
    assert evidence["supported"] is True
    assert reranked["results"][0]["index"] == 1

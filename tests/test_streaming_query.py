from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.query import router as query_router
from app.core.config import Settings
from app.core.dependencies import (
    get_agent_orchestrator,
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
    get_router,
    get_session_memory,
    get_study_agent,
    get_synthesis_agent,
)
from app.core.schemas import AgentStep, ChunkRecord, RouteDecision
from app.services.memory.session_memory import SessionMemory
from app.storage.metadata_store import MetadataStore


class _Retriever:
    def retrieve(self, _question, top_k=5, workspace_id=None, document_ids=None):
        return [
            ChunkRecord(
                chunk_id="chunk-1",
                document_id="doc-1",
                workspace_id=workspace_id or "default",
                filename="contract.pdf",
                page_number=2,
                text="The termination clause requires thirty days notice.",
                metadata={"content_type": "text"},
            )
        ]


class _Reranker:
    def rerank(self, _question, chunks, top_n):
        return chunks[:top_n]

    def status(self):
        return {"status": "ok"}


class _Router:
    def route(self, _question, session_id=None):
        return RouteDecision(route="factual", requested_top_k=5)


class _LLM:
    provider_name = "grounded_fallback"
    model_name = "test"

    def generate(self, _question, _contexts, require_citations=True, response_preferences=None):
        return "Termination requires thirty days notice. [Source: contract.pdf p.2 chunk-1]"

    def stream_generate(self, _question, _contexts, require_citations=True, response_preferences=None):
        for token in ["Termination ", "requires ", "thirty ", "days ", "notice. ", "[Source: contract.pdf p.2 chunk-1]"]:
            yield token


class _EvalLogger:
    def log_query(self, _question, _response, _trace):
        return "query-stream"


class _Planner:
    def plan(self, *_args, **_kwargs):
        return []


class _Engine:
    pass


class _DisabledGraph:
    enabled = False


def _step(agent: str, action: str = "test") -> AgentStep:
    return AgentStep(step_id=f"{agent}-{action}", agent_name=agent, action=action, output_summary="test")


class _ContextAgent:
    def build(self, **_kwargs):
        return {}, _step("ContextAgent", "build")

    def remember_turn(self, **_kwargs):
        return None


class _RetrievalAgent:
    def plan(self, requested_top_k=5, **_kwargs):
        return {"top_k": requested_top_k, "strategy": "hybrid", "use_graph": False}, _step("RetrievalAgent", "plan")


class _ObjectiveAgent:
    def annotate(self, *_args, **_kwargs):
        return "", _step("ObjectiveAgent", "annotate")


class _SynthesisAgent:
    def build_preferences(self, **_kwargs):
        return {}, _step("SynthesisAgent", "preferences")


class _EvidenceAgent:
    def build_canvas(self, **_kwargs):
        return None, _step("EvidenceAgent", "canvas")


class _AgentOrchestrator:
    def start_run(self, *_args, **_kwargs):
        return "run"

    def fail_run(self, **_kwargs):
        return None

    def plan_pipeline(self, **_kwargs):
        return [], _step("AgentOrchestrator", "plan")

    def retry_queries(self, query, **_kwargs):
        return [query]

    def graph_trace_step(self, *_args, **_kwargs):
        return _step("AgentOrchestrator", "graph")

    def verification_step(self, **_kwargs):
        return False, _kwargs.get("confidence", 1.0), _step("AgentOrchestrator", "verify")

    def finalize_response(self, response, **_kwargs):
        return response


def test_streaming_query_emits_token_and_final_events(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(
        ENABLE_ROUTER=True,
        ENABLE_HYBRID=True,
        ENABLE_RERANKER=False,
        MIN_CONFIDENCE_TO_ANSWER=0.1,
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        REQUIRE_AUTH=False,
        ENABLE_LOCAL_USER_FALLBACK=True,
        DATABASE_BACKEND="sqlite",
        ENABLE_GRAPH_MEMORY=False,
        ENABLE_REAL_ORCHESTRATOR=False,
    )
    app = FastAPI()
    app.include_router(query_router)
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_router] = lambda: _Router()
    app.dependency_overrides[get_dense_retriever] = lambda: _Retriever()
    app.dependency_overrides[get_hybrid_retriever] = lambda: _Retriever()
    app.dependency_overrides[get_reranker] = lambda: _Reranker()
    app.dependency_overrides[get_query_planner] = lambda: _Planner()
    app.dependency_overrides[get_multistep_engine] = lambda: _Engine()
    app.dependency_overrides[get_session_memory] = lambda: SessionMemory()
    app.dependency_overrides[get_primary_llm] = lambda: _LLM()
    app.dependency_overrides[get_fallback_llm] = lambda: None
    app.dependency_overrides[get_eval_logger] = lambda: _EvalLogger()
    app.dependency_overrides[get_graph_repository] = lambda: _DisabledGraph()
    app.dependency_overrides[get_context_agent] = lambda: _ContextAgent()
    app.dependency_overrides[get_retrieval_agent] = lambda: _RetrievalAgent()
    app.dependency_overrides[get_evidence_agent] = lambda: _EvidenceAgent()
    app.dependency_overrides[get_legal_agent] = lambda: _ObjectiveAgent()
    app.dependency_overrides[get_study_agent] = lambda: _ObjectiveAgent()
    app.dependency_overrides[get_enterprise_agent] = lambda: _ObjectiveAgent()
    app.dependency_overrides[get_synthesis_agent] = lambda: _SynthesisAgent()
    app.dependency_overrides[get_agent_orchestrator] = lambda: _AgentOrchestrator()

    with TestClient(app) as client:
        with client.stream(
                "POST",
                "/chat/query/stream",
                json={"question": "What is termination notice?", "workspace_id": "default", "return_evidence_canvas": False},
            ) as response:
            body = "".join(response.iter_text())

    assert "event: retrieval_started" in body
    assert "event: retrieval_completed" in body
    assert "event: generation_started" in body
    assert "event: done" in body
    assert "event: completed" in body
    assert body.index("event: token") < body.index("event: completed")
    assert "Termination requires thirty days notice" in body
    assert "evidence_canvas" in body

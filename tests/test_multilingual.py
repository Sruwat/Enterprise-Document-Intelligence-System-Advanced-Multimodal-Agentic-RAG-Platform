from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.query import _abstain_message, router as query_router
from app.core.config import Settings
from app.core.dependencies import (
    get_app_settings,
    get_context_agent,
    get_dense_retriever,
    get_eval_logger,
    get_fallback_llm,
    get_graph_repository,
    get_hybrid_retriever,
    get_metadata_store,
    get_multistep_engine,
    get_primary_llm,
    get_query_planner,
    get_reranker,
    get_redis_service,
    get_router,
    get_session_memory,
)
from app.core.schemas import ChunkRecord, RouteDecision
from app.services.language import LanguagePreferenceService
from app.services.agents.context_agent import ContextAgent
from app.services.memory.session_memory import SessionMemory
from app.services.planner.query_understanding import QueryUnderstandingService
from app.storage.metadata_store import MetadataStore


class _CapturingRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, question, top_k=5, workspace_id=None, document_ids=None):
        self.queries.append(question)
        return [
            ChunkRecord(
                chunk_id="chunk-1",
                document_id="doc-1",
                workspace_id=workspace_id or "default",
                filename="contract.pdf",
                page_number=2,
                text="The termination clause requires thirty days notice.",
                metadata={"content_type": "text"},
                combined_score=0.9,
            )
        ][:top_k]


class _Reranker:
    def rerank(self, _question, chunks, top_n):
        for chunk in chunks:
            chunk.rerank_score = 0.9
        return chunks[:top_n]


class _Router:
    def route(self, _question, session_id=None):
        return RouteDecision(route="factual", requested_top_k=5)


class _LanguageEchoLLM:
    provider_name = "grounded_fallback"
    model_name = "test"

    def generate(self, _question, _contexts, require_citations=True, response_preferences=None):
        language = (response_preferences or {}).get("language")
        if language == "hindi":
            return "समाप्ति के लिए तीस दिन का नोटिस चाहिए. [Source: contract.pdf p.2 chunk-1]"
        if language == "hinglish":
            return "Termination ke liye thirty days notice chahiye. [Source: contract.pdf p.2 chunk-1]"
        if language == "spanish":
            return "La terminacion requiere aviso de treinta dias. [Source: contract.pdf p.2 chunk-1]"
        return "Termination requires thirty days notice. [Source: contract.pdf p.2 chunk-1]"


class _EvalLogger:
    def __init__(self) -> None:
        self.payloads = []

    def log_query(self, _question, response, _trace):
        self.payloads.append(response)
        return "query-multilingual"


class _Planner:
    def plan(self, *_args, **_kwargs):
        return []


class _Engine:
    pass


class _Graph:
    enabled = False

    def search_graph(self, *_args, **_kwargs):
        return []


def _client(tmp_path, retriever: _CapturingRetriever, store: MetadataStore | None = None):
    store = store or MetadataStore(tmp_path / "metadata.db")
    settings = Settings(
        ENABLE_ROUTER=True,
        ENABLE_HYBRID=True,
        ENABLE_RERANKER=True,
        MIN_CONFIDENCE_TO_ANSWER=0.1,
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        REQUIRE_AUTH=False,
        ENABLE_LOCAL_USER_FALLBACK=True,
        DATABASE_BACKEND="sqlite",
        ENABLE_GRAPH_MEMORY=False,
        ENABLE_REDIS=False,
        ENABLE_REAL_ORCHESTRATOR=False,
    )
    app = FastAPI()
    app.include_router(query_router)
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_router] = lambda: _Router()
    app.dependency_overrides[get_dense_retriever] = lambda: retriever
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    app.dependency_overrides[get_reranker] = lambda: _Reranker()
    app.dependency_overrides[get_query_planner] = lambda: _Planner()
    app.dependency_overrides[get_multistep_engine] = lambda: _Engine()
    app.dependency_overrides[get_session_memory] = lambda: SessionMemory()
    app.dependency_overrides[get_context_agent] = lambda: ContextAgent(store, SessionMemory())
    app.dependency_overrides[get_primary_llm] = lambda: _LanguageEchoLLM()
    app.dependency_overrides[get_fallback_llm] = lambda: None
    app.dependency_overrides[get_graph_repository] = lambda: _Graph()
    app.dependency_overrides[get_eval_logger] = lambda: _EvalLogger()
    app.dependency_overrides[get_redis_service] = lambda: None
    return TestClient(app), store


def test_language_detection_supports_hindi_hinglish_english_and_spanish():
    service = LanguagePreferenceService()

    assert service.detect("समाप्ति नोटिस क्या है?") == "hindi"
    assert service.detect("Graph kya batao") == "hinglish"
    assert service.detect("What is the notice period?") == "english"
    assert service.detect("¿Qué dice el contrato sobre terminación?") == "spanish"


def test_query_understanding_adds_english_rewrite_for_cross_lingual_retrieval():
    hindi = QueryUnderstandingService().understand("समाप्ति नोटिस क्या है?", language="auto")
    spanish = QueryUnderstandingService().understand("¿Qué dice el contrato sobre terminación?", language="auto")

    assert hindi.answer_language == "hindi"
    assert "termination notice what" in hindi.retrieval_query
    assert spanish.answer_language == "spanish"
    assert "contract" in spanish.retrieval_query
    assert "termination" in spanish.retrieval_query


def test_hindi_query_returns_hindi_answer_with_preserved_citation(tmp_path):
    retriever = _CapturingRetriever()
    client, _store = _client(tmp_path, retriever)

    response = client.post("/chat/query", json={"question": "समाप्ति नोटिस क्या है?", "workspace_id": "default"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer_language"] == "hindi"
    assert "तीस दिन" in payload["answer"]
    assert "[Source: contract.pdf p.2 chunk-1]" in payload["answer"]
    assert "termination notice what" in retriever.queries[-1]


def test_hinglish_query_returns_hinglish_answer_with_citation(tmp_path):
    retriever = _CapturingRetriever()
    client, _store = _client(tmp_path, retriever)

    response = client.post("/chat/query", json={"question": "Termination kya hai?", "workspace_id": "default"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer_language"] == "hinglish"
    assert "chahiye" in payload["answer"]
    assert "[Source: contract.pdf p.2 chunk-1]" in payload["answer"]


def test_spanish_query_returns_spanish_answer_with_citation(tmp_path):
    retriever = _CapturingRetriever()
    client, _store = _client(tmp_path, retriever)

    response = client.post("/chat/query", json={"question": "¿Qué dice el contrato sobre terminación?", "workspace_id": "default"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer_language"] == "spanish"
    assert "treinta dias" in payload["answer"]
    assert "[Source: contract.pdf p.2 chunk-1]" in payload["answer"]
    assert "contract" in retriever.queries[-1]


def test_session_response_language_preference_persists_for_followup(tmp_path):
    retriever = _CapturingRetriever()
    store = MetadataStore(tmp_path / "metadata.db")
    session = store.create_chat_session("default", None, "auto", "normal", response_language="spanish")
    client, _store = _client(tmp_path, retriever, store=store)

    response = client.post("/chat/query", json={"question": "What is termination notice?", "workspace_id": "default", "session_id": session.session_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer_language"] == "spanish"
    messages = store.list_chat_messages(session.session_id)
    assert messages[0].language == "english"
    assert messages[1].language == "spanish"


def test_abstain_messages_are_localized():
    assert _abstain_message("hindi").startswith("मुझे")
    assert _abstain_message("spanish").startswith("No encontre")

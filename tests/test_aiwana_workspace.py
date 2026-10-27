from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.query import (
    _abstain_message,
    _dynamic_context_selection,
    _effective_confidence,
    _effective_coverage,
    _prioritize_answer_evidence,
    _question_coverage,
    router as query_router,
)
from app.api.routes.ingest import public_router as sources_router
from app.api.routes.workspaces import router as workspace_router
from app.core.config import Settings
from app.core.dependencies import (
    get_app_settings,
    get_context_agent,
    get_dense_retriever,
    get_eval_logger,
    get_fallback_llm,
    get_graph_repository,
    get_hybrid_retriever,
    get_indexer,
    get_metadata_store,
    get_multistep_engine,
    get_primary_llm,
    get_query_planner,
    get_reranker,
    get_redis_service,
    get_router,
    get_session_memory,
)
from app.core.schemas import ChunkRecord, DocumentRecord, IngestResponse, RouteDecision
from app.services.guardrails.citation import build_evidence
from app.services.agents.context_agent import ContextAgent
from app.services.ingestion.multimodal import MultimodalAssetExtractor
from app.services.llm.llm_provider import GroundedFallbackLLMProvider
from app.services.memory.session_memory import SessionMemory
from app.services.planner.query_understanding import QueryUnderstandingService
from app.services.router.intent_classifier import HybridIntentClassifier
from app.storage.metadata_store import MetadataStore


def test_workspace_storage_scopes_documents_and_sessions(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    first = store.create_workspace("Biology")
    second = store.create_workspace("Finance", private_mode=True)
    store.upsert_document(
        DocumentRecord(
            document_id="doc-1",
            workspace_id=first.workspace_id,
            filename="chapter.pdf",
            source_path="chapter.pdf",
            fingerprint="fp",
            status="indexed",
            page_count=1,
            ingested_at=datetime.utcnow(),
        )
    )
    session = store.create_chat_session(second.workspace_id, "Private", "hinglish", "layman")

    assert [doc.document_id for doc in store.list_documents(workspace_id=first.workspace_id)] == ["doc-1"]
    assert store.list_documents(workspace_id=second.workspace_id) == []
    assert store.get_workspace(second.workspace_id).private_mode is True
    assert store.get_chat_session(session.session_id).workspace_id == second.workspace_id


def test_query_understanding_translates_hinglish_for_retrieval():
    understanding = QueryUnderstandingService().understand("Graph kya batao", language="auto", explanation_level="layman")

    assert understanding.answer_language == "hinglish"
    assert understanding.retrieval_query == "graph what explain"
    assert understanding.interpreted_query is not None
    assert _abstain_message("hinglish").startswith("Mujhe aapke documents")


def test_broad_pdf_about_question_does_not_zero_coverage():
    chunks = [
        ChunkRecord(
            chunk_id="summary",
            document_id="doc-1",
            filename="report.pdf",
            page_number=3,
            text="Executive Summary Suryagram is a fictional rural learning-centre pilot with solar power, safe-water infrastructure and offline digital learning.",
        )
    ]

    assert _question_coverage("whats that pdf about", chunks) == 1.0
    assert _effective_coverage("Give me a 5 bullet summary of this report.", chunks, "summary") >= 0.75
    assert _effective_coverage("What are the main outcomes mentioned in the report?", chunks, "summary") >= 0.7
    assert _effective_confidence(0.22, 0.9, "summary", chunks, 1, 0.42) >= 0.42


def test_main_outcomes_routes_as_summary():
    result = HybridIntentClassifier().classify("What are the main outcomes mentioned in the report?")

    assert result.intent == "summary"


def test_summary_context_keeps_broader_evidence_and_demotes_test_pages():
    chunks = [
        ChunkRecord(chunk_id="map", document_id="doc-1", filename="report.pdf", page_number=19, text="Evidence inventory. Citation validation prompt Give three major outcomes."),
        ChunkRecord(chunk_id="attendance", document_id="doc-1", filename="report.pdf", page_number=8, text="Attendance outcomes improved for grades 6 to 8."),
        ChunkRecord(chunk_id="summary", document_id="doc-1", filename="report.pdf", page_number=3, text="Executive Summary. Attendance, learning, solar and water outcomes improved."),
    ]

    selected = _dynamic_context_selection(chunks, "summary", 6)
    prioritized = _prioritize_answer_evidence("What are the main outcomes mentioned in the report?", selected)

    assert [chunk.chunk_id for chunk in selected] == ["map", "attendance", "summary"]
    assert prioritized[0].chunk_id == "attendance"
    assert prioritized[-1].chunk_id == "map"


def test_image_source_creates_visual_evidence_without_optional_ocr(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.ingestion.multimodal.Image", None)
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"placeholder")
    page = MultimodalAssetExtractor(tmp_path / "previews", enable_ocr=False).parse_image(image_path)[0]
    chunk = ChunkRecord(
        chunk_id="chunk-1",
        document_id="doc-1",
        filename=image_path.name,
        page_number=1,
        text=page["text"],
        metadata={"content_type": "visual_text", "multimodal_assets": page["metadata"]},
    )

    evidence, cards = build_evidence([chunk])

    assert evidence[0].preview_path == str(image_path)
    assert cards[0].visual_type == "image"


def test_text_page_preview_is_not_exposed_as_visual_evidence_card():
    chunk = ChunkRecord(
        chunk_id="chunk-page",
        document_id="doc-1",
        filename="report.pdf",
        page_number=16,
        text="Glossary and bilingual text.",
        metadata={
            "content_type": "text",
            "multimodal_assets": {
                "visual_assets": [{"anchor_id": "page-16", "visual_type": "page", "preview_path": "page-16.png"}]
            },
        },
    )

    _, cards = build_evidence([chunk])

    assert cards == []


def test_local_fallback_prefers_evidence_page_over_question_bank():
    provider = GroundedFallbackLLMProvider()
    answer = provider.generate(
        "What was the total solar generation in 2025?",
        [
            "[Source: report.pdf p.20 question-bank]\nQuestion Bank. What was annual solar generation in 2025? 98.9 MWh | p.6.",
            "[Source: report.pdf p.6 evidence]\nEnergy Performance. Quarterly generation totalled 98.9 MWh, with Q4 the strongest period at 30.6 MWh.",
        ],
        response_preferences={"language": "hinglish", "intent": "factual", "answer_mode": "answer"},
    )

    assert "p.6 evidence" in answer
    assert "Question Bank" not in answer
    assert "98.9 MWh" in answer
    assert "total" in answer


def test_local_fallback_ignores_embedded_prompt_for_chart_answer():
    provider = GroundedFallbackLLMProvider()
    answer = provider.generate(
        "Explain the water availability graph in layman Hinglish.",
        [
            "[Source: report.pdf p.7 chart; content_type=visual_text]\nWater Security. HINGLISH PROMPT Paani availability July ke baad kyun badhi? Daily availability averaged 569 litres across the year and increased sharply during monsoon recharge between July and September. Availability peaked in August at 770 L/day.",
            "[Source: report.pdf p.16 language; content_type=text]\nHINGLISH (ROMAN) Tank students ke peene ke liye treated rainwater store karta hai. In August, availability reached 770 litres per day.",
        ],
        response_preferences={"language": "hinglish", "intent": "chart_analysis", "answer_mode": "answer"},
    )

    assert "HINGLISH PROMPT" not in answer
    assert "Daily availability ka average 569" in answer
    assert "p.7 chart" in answer


class _SourceIndexer:
    def ingest_source(self, path, workspace_id="default", progress_callback=None):
        if progress_callback:
            progress_callback("parsing", 20, "Parsing")
            progress_callback("ready", 100, "Ready")
        return IngestResponse(
            document=DocumentRecord(
                document_id="doc-source",
                workspace_id=workspace_id,
                filename=Path(path).name,
                source_path=str(path),
                fingerprint="fp",
                status="indexed",
                page_count=1,
                ingested_at=datetime.utcnow(),
            ),
            chunks_created=1,
            indexed=True,
        )


def test_workspace_text_source_creates_ready_ingestion_job(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        REQUIRE_AUTH=False,
        ENABLE_LOCAL_USER_FALLBACK=True,
        DATABASE_BACKEND="sqlite",
        ENABLE_REDIS=False,
    )
    app = FastAPI()
    app.include_router(workspace_router)
    app.include_router(sources_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_indexer] = lambda: _SourceIndexer()
    app.dependency_overrides[get_redis_service] = lambda: None

    with TestClient(app) as client:
        workspace = client.post("/workspaces", json={"name": "Science"}).json()
        submitted = client.post(
            f"/workspaces/{workspace['workspace_id']}/sources/text",
            json={"title": "Gravity", "text": "Gravity attracts masses."},
        )
        job = client.get(f"/ingestions/{submitted.json()['job_id']}").json()

    assert submitted.status_code == 202
    assert job["status"] == "ready"
    assert job["document_id"] == "doc-source"


class _Retriever:
    def __init__(self, chunks):
        self.chunks = chunks

    def retrieve(self, _question, top_k=5, workspace_id=None, document_ids=None):
        return [chunk for chunk in self.chunks if chunk.workspace_id == workspace_id][:top_k]


class _Reranker:
    def rerank(self, _question, chunks, top_n):
        for chunk in chunks:
            chunk.rerank_score = 0.9
        return chunks[:top_n]


class _Router:
    def route(self, _question, session_id=None):
        return RouteDecision(route="factual", requested_top_k=5)


class _LLM:
    provider_name = "grounded_fallback"
    model_name = "test"

    def generate(self, _question, _contexts, require_citations=True, response_preferences=None):
        return "From your document: A chart shows growth. [Source: chart.png p.1 chunk-1]"


class _EvalLogger:
    def log_query(self, _question, _response, _trace):
        return "query-1"


class _Planner:
    def plan(self, *_args, **_kwargs):
        return []


class _Engine:
    pass


def test_chat_query_returns_hinglish_visual_contract(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    chunk = ChunkRecord(
        chunk_id="chunk-1",
        document_id="doc-1",
        workspace_id="default",
        filename="chart.png",
        page_number=1,
        text="The chart shows revenue growth.",
        rerank_score=0.9,
        metadata={
            "content_type": "visual_text",
            "multimodal_assets": {
                "visual_assets": [
                    {"anchor_id": "asset-1", "visual_type": "chart", "preview_path": "chart.png", "bbox": None}
                ]
            },
        },
    )
    settings = Settings(
        ENABLE_ROUTER=True,
        ENABLE_HYBRID=True,
        ENABLE_RERANKER=True,
        RETRIEVAL_CANDIDATE_POOL=5,
        MAX_CONTEXT_CHUNKS=5,
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
    app.dependency_overrides[get_dense_retriever] = lambda: _Retriever([chunk])
    app.dependency_overrides[get_hybrid_retriever] = lambda: _Retriever([chunk])
    app.dependency_overrides[get_reranker] = lambda: _Reranker()
    app.dependency_overrides[get_query_planner] = lambda: _Planner()
    app.dependency_overrides[get_multistep_engine] = lambda: _Engine()
    app.dependency_overrides[get_session_memory] = lambda: SessionMemory()
    app.dependency_overrides[get_primary_llm] = lambda: _LLM()
    app.dependency_overrides[get_fallback_llm] = lambda: None
    app.dependency_overrides[get_eval_logger] = lambda: _EvalLogger()
    app.dependency_overrides[get_graph_repository] = lambda: type("DisabledGraph", (), {"enabled": False})()
    app.dependency_overrides[get_context_agent] = lambda: ContextAgent(store, SessionMemory())
    app.dependency_overrides[get_redis_service] = lambda: None

    with TestClient(app) as client:
        response = client.post(
            "/chat/query",
            json={
                "question": "Graph kya batao",
                "workspace_id": "default",
                "language": "auto",
                "answer_mode": "explain_visual",
                "explanation_level": "layman",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "visual_question"
    assert payload["answer_language"] == "hinglish"
    assert payload["visual_cards"][0]["visual_type"] == "chart"
    assert payload["evidence"][0]["anchor_id"] == "asset-1"

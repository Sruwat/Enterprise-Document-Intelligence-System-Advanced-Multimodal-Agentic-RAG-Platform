from functools import lru_cache

from app.core.logging import get_logger

from app.core.config import Settings, get_settings
from app.services.evaluation.logger import EvaluationLogger
from app.services.evaluation.metrics import EvaluationService
from app.services.email import EmailSender
from app.services.agents.context_agent import ContextAgent
from app.services.agents.evidence_agent import EvidenceAgent
from app.services.agents.objective_agents import EnterpriseAgent, LegalAgent, StudyAgent
from app.services.agents.retrieval_agent import RetrievalAgent
from app.services.agents.synthesis_agent import SynthesisAgent
from app.services.agentic import AgenticQueryEngine
from app.services.cache import QueryCache
from app.services.ingestion.chunker import RecursiveChunker
from app.services.ingestion.embedder import BgeM3EmbeddingProvider, SentenceTransformerEmbeddingProvider
from app.services.ingestion.indexer import DocumentIndexer
from app.services.ingestion.multimodal import MultimodalAssetExtractor
from app.services.ingestion.parser import PDFParser
from app.services.graph_memory import DisabledGraphRepository, PostgresGraphRepository
from app.services.llm.fallback_provider import GroundedFallbackLLMProvider
from app.services.llm.llm_provider import build_llm_providers
from app.services.memory.session_memory import SessionMemory
from app.services.redis_client import RedisService
from app.services.orchestrator.multistep_engine import MultiStepQueryEngine
from app.services.orchestrator.agent_orchestrator import AgentOrchestrator
from app.services.planner.query_planner import QueryPlanner
from app.services.reranker.cross_encoder import CrossEncoderReranker, DisabledReranker
from app.services.retrieval.dense import DenseRetriever
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.sparse import BM25Retriever
from app.services.router.intent_classifier import HybridIntentClassifier
from app.db.repositories.postgres_metadata import PostgresMetadataRepository
from app.storage.bm25_store import BM25IndexStore
from app.storage.metadata_store import MetadataStore
from app.storage.qdrant import QdrantVectorStore
from app.services.worker import AiwanaWorker, WorkerQueue
from app.services.huggingface import HuggingFaceProviderRegistry

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_metadata_store():
    settings = get_settings()
    if settings.database_backend.lower() == "postgres":
        return PostgresMetadataRepository(settings.database_url)
    return MetadataStore(settings.metadata_db)


@lru_cache(maxsize=1)
def get_bm25_store() -> BM25IndexStore:
    store = BM25IndexStore()
    chunks = get_metadata_store().list_chunks()
    if chunks:
        store.upsert_documents({chunk.chunk_id: chunk.text for chunk in chunks})
    return store


@lru_cache(maxsize=1)
def get_vector_store() -> QdrantVectorStore:
    settings = get_settings()
    store = QdrantVectorStore(
        settings.qdrant_url,
        settings.qdrant_collection,
        fallback_url=settings.qdrant_local_fallback_url,
        use_named_vectors=settings.enable_named_vectors,
        use_sparse_vectors=settings.enable_bge_m3_sparse,
    )
    active_location = store.get_active_location()
    if active_location != settings.qdrant_url:
        logger.warning("Qdrant primary unavailable, using fallback store at %s", active_location)
    return store


@lru_cache(maxsize=1)
def get_embedding_provider() -> SentenceTransformerEmbeddingProvider:
    settings = get_settings()
    if "bge-m3" in settings.embedding_model.lower() or "bge-m3" in str(settings.embedding_model_path).lower():
        return BgeM3EmbeddingProvider(settings.embedding_model_path, settings.embedding_batch_size, enable_sparse=settings.enable_bge_m3_sparse)
    return SentenceTransformerEmbeddingProvider(settings.embedding_model_path, settings.embedding_batch_size)


@lru_cache(maxsize=1)
def get_pdf_parser() -> PDFParser:
    settings = get_settings()
    return PDFParser(asset_extractor=MultimodalAssetExtractor(settings.data_dir / "previews", enable_ocr=settings.enable_multimodal))


@lru_cache(maxsize=1)
def get_chunker() -> RecursiveChunker:
    settings = get_settings()
    return RecursiveChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)


@lru_cache(maxsize=1)
def get_indexer() -> DocumentIndexer:
    return DocumentIndexer(
        parser=get_pdf_parser(),
        chunker=get_chunker(),
        embedder=get_embedding_provider(),
        vector_store=get_vector_store(),
        sparse_store=get_bm25_store(),
        metadata_store=get_metadata_store(),
        graph_repository=get_graph_repository(),
    )


@lru_cache(maxsize=1)
def get_graph_repository():
    settings = get_settings()
    if not settings.enable_graph_memory:
        return DisabledGraphRepository()
    if settings.graph_backend.lower() != "postgres":
        logger.warning("Unsupported graph backend %s; graph memory disabled.", settings.graph_backend)
        return DisabledGraphRepository()
    if settings.database_backend.lower() != "postgres":
        logger.warning("Graph memory requires DATABASE_BACKEND=postgres; graph memory disabled for local SQLite metadata.")
        return DisabledGraphRepository()
    return PostgresGraphRepository(settings.database_url)


@lru_cache(maxsize=1)
def get_sparse_retriever() -> BM25Retriever:
    return BM25Retriever(get_bm25_store(), get_metadata_store())


@lru_cache(maxsize=1)
def get_dense_retriever() -> DenseRetriever:
    settings = get_settings()
    return DenseRetriever(get_vector_store(), get_embedding_provider(), get_metadata_store(), settings.default_top_k)


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoderReranker | DisabledReranker:
    settings = get_settings()
    if not settings.enable_reranker:
        return DisabledReranker()
    return CrossEncoderReranker(
        settings.reranker_model_path,
        max_candidates=settings.rerank_max_candidates,
        batch_size=settings.rerank_batch_size,
        timeout_seconds=settings.rerank_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_session_memory() -> SessionMemory:
    settings = get_settings()
    redis_service = get_redis_service() if settings.enable_redis and settings.session_backend == "redis" else None
    return SessionMemory(max_turns=settings.session_memory_turns, redis_service=redis_service)


@lru_cache(maxsize=1)
def get_redis_service() -> RedisService:
    settings = get_settings()
    return RedisService(settings.redis_url, enabled=settings.enable_redis)


@lru_cache(maxsize=1)
def get_query_cache() -> QueryCache:
    settings = get_settings()
    redis_service = get_redis_service() if settings.enable_redis and settings.cache_backend == "redis" else None
    return QueryCache(redis_service=redis_service, ttl_seconds=settings.retrieval_cache_ttl_seconds)


@lru_cache(maxsize=1)
def get_router() -> HybridIntentClassifier:
    return HybridIntentClassifier(llm_provider=get_primary_llm(), memory=get_session_memory())


@lru_cache(maxsize=1)
def get_hybrid_retriever() -> HybridRetriever:
    settings = get_settings()
    return HybridRetriever(
        dense_retriever=get_dense_retriever(),
        sparse_retriever=get_sparse_retriever(),
        dense_weight=settings.dense_weight,
        sparse_weight=settings.sparse_weight,
    )


@lru_cache(maxsize=1)
def get_llm_providers():
    settings = get_settings()
    return build_llm_providers(settings)


@lru_cache(maxsize=1)
def get_primary_llm():
    return get_llm_providers()[0]


@lru_cache(maxsize=1)
def get_fallback_llm():
    return get_llm_providers()[1]


@lru_cache(maxsize=1)
def get_eval_logger() -> EvaluationLogger:
    return EvaluationLogger(get_metadata_store())


@lru_cache(maxsize=1)
def get_evaluation_service() -> EvaluationService:
    return EvaluationService(get_eval_logger(), get_metadata_store(), query_runner=_run_evaluation_query)


def _run_evaluation_query(case: dict):
    from app.api.routes.query import query_documents
    from app.core.schemas import QueryRequest

    request = QueryRequest(
        question=case.get("query") or case.get("question") or "",
        workspace_id=case.get("workspace_id", "default"),
        document_ids=case.get("document_ids", []),
        language=case.get("language", "auto"),
        input_language=case.get("input_language"),
        response_language=case.get("response_language"),
        answer_mode=case.get("answer_mode", "answer"),
        explanation_level=case.get("explanation_level", "normal"),
        objective_profile=case.get("objective_profile", "general"),
        analysis_mode=case.get("analysis_mode", "quick"),
        route_hint=case.get("route_hint"),
        mode=case.get("mode", "single"),
        top_k=int(case.get("top_k", 5)),
        return_evidence_canvas=True,
        return_steps=True,
    )
    return query_documents(
        request,
        settings=get_app_settings(),
        agent_orchestrator=get_agent_orchestrator(),
        router_service=get_router(),
        dense_retriever=get_dense_retriever(),
        hybrid_retriever=get_hybrid_retriever(),
        reranker=get_reranker(),
        planner=get_query_planner(),
        multistep_engine=get_multistep_engine(),
        session_memory=get_session_memory(),
        primary_llm=get_primary_llm(),
        fallback_llm=get_fallback_llm(),
        graph_repository=get_graph_repository(),
        eval_logger=get_eval_logger(),
        metadata_store=get_metadata_store(),
        context_agent=get_context_agent(),
        retrieval_agent=get_retrieval_agent(),
        evidence_agent=get_evidence_agent(),
        legal_agent=get_legal_agent(),
        study_agent=get_study_agent(),
        enterprise_agent=get_enterprise_agent(),
        synthesis_agent=get_synthesis_agent(),
        agentic_engine=get_agentic_query_engine(),
        user=get_metadata_store().get_user("local-user"),
    )


@lru_cache(maxsize=1)
def get_email_sender() -> EmailSender:
    return EmailSender(get_settings())


@lru_cache(maxsize=1)
def get_query_planner() -> QueryPlanner:
    return QueryPlanner(memory=get_session_memory())


@lru_cache(maxsize=1)
def get_multistep_engine() -> MultiStepQueryEngine:
    return MultiStepQueryEngine(
        settings=get_settings(),
        dense_retriever=get_dense_retriever(),
        hybrid_retriever=get_hybrid_retriever(),
        reranker=get_reranker(),
    )


@lru_cache(maxsize=1)
def get_agent_orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator()


def get_app_settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def get_context_agent() -> ContextAgent:
    return ContextAgent(get_metadata_store(), get_session_memory())


@lru_cache(maxsize=1)
def get_retrieval_agent() -> RetrievalAgent:
    return RetrievalAgent()


@lru_cache(maxsize=1)
def get_evidence_agent() -> EvidenceAgent:
    return EvidenceAgent()


@lru_cache(maxsize=1)
def get_legal_agent() -> LegalAgent:
    return LegalAgent()


@lru_cache(maxsize=1)
def get_study_agent() -> StudyAgent:
    return StudyAgent()


@lru_cache(maxsize=1)
def get_enterprise_agent() -> EnterpriseAgent:
    return EnterpriseAgent()


@lru_cache(maxsize=1)
def get_synthesis_agent() -> SynthesisAgent:
    return SynthesisAgent()


@lru_cache(maxsize=1)
def get_agentic_query_engine() -> AgenticQueryEngine:
    return AgenticQueryEngine()


@lru_cache(maxsize=1)
def get_worker_queue() -> WorkerQueue:
    return WorkerQueue(get_redis_service())


@lru_cache(maxsize=1)
def get_aiwana_worker() -> AiwanaWorker:
    return AiwanaWorker(queue=get_worker_queue(), indexer=get_indexer(), metadata_store=get_metadata_store(), redis_service=get_redis_service(), query_cache=get_query_cache())


@lru_cache(maxsize=1)
def get_huggingface_registry() -> HuggingFaceProviderRegistry:
    settings = get_settings()
    overrides = {}
    if settings.huggingface_task_overrides:
        for item in settings.huggingface_task_overrides.split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                overrides[key.strip()] = value.strip()
    task_enables = {}
    task_enables.update(
        {
            "embedding": settings.hf_embeddings_enabled,
            "reranking": settings.hf_reranking_enabled,
            "entity_extraction": settings.hf_entity_extraction_enabled,
            "evidence_checking": settings.hf_evidence_checking_enabled,
            "document_classification": settings.hf_classification_enabled,
            "image_captioning": settings.hf_captioning_enabled,
            "ocr_vlm": settings.hf_ocr_vlm_enabled,
        }
    )
    if settings.huggingface_task_enables:
        for item in settings.huggingface_task_enables.split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                task_enables[key.strip()] = value.strip().lower() in {"1", "true", "yes", "on"}
    return HuggingFaceProviderRegistry(
        enabled=settings.huggingface_provider_enabled,
        cache_dir=settings.huggingface_model_cache,
        overrides=overrides,
        task_enables=task_enables,
        max_seconds=settings.huggingface_max_seconds,
        max_memory_mb=settings.huggingface_max_memory_mb,
    )

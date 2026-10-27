from __future__ import annotations

import os
from pathlib import Path

from app.core.dependencies import (
    get_bm25_store,
    get_embedding_provider,
    get_metadata_store,
    get_primary_llm,
    get_reranker,
    get_redis_service,
    get_settings,
    get_vector_store,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def validate_startup() -> None:
    settings = get_settings()
    os.environ.setdefault("HF_HOME", settings.hf_home)
    if settings.app_env.lower() == "production" and not settings.auth_secret:
        raise RuntimeError("AUTH_SECRET must be configured in production.")
    if settings.llm_privacy_mode == "private_only" and settings.llm_provider not in {"openai_compatible", "private", "ollama"}:
        raise RuntimeError("Private-only AI mode blocks public LLM providers. Configure openai_compatible/private/ollama.")

    llm = get_primary_llm()
    logger.info("LLM provider mode: %s (%s)", llm.provider_name, llm.model_name)

    redis_service = get_redis_service()
    redis_status = redis_service.status()
    if settings.app_env.lower() == "production" and settings.enable_redis and redis_status.get("status") != "ok":
        raise RuntimeError(f"Redis is required in production but unavailable: {redis_status.get('detail', 'unknown error')}")
    if settings.app_env.lower() == "production" and not settings.enable_redis:
        raise RuntimeError("Redis must be enabled in production.")

    vector_store = get_vector_store()
    if vector_store.is_available():
        logger.info("Qdrant store ready at %s", vector_store.get_active_location())
    else:
        logger.warning("Qdrant store is unavailable. Queries will fail until a store is reachable.")

    model_path = Path(settings.embedding_model_path)
    if not model_path.exists():
        raise RuntimeError(
            f"Embedding model directory is missing: {model_path}. "
            f"Bundle {settings.embedding_model} into the image or download it locally before startup."
        )

    embedder = get_embedding_provider()
    probe = embedder.embed_query("startup validation")
    logger.info(
        "Embedding model ready from local path: %s (dimension=%s)",
        model_path,
        len(probe),
    )
    reranker = get_reranker()
    reranker_status = reranker.status()
    if settings.enable_reranker:
        if reranker_status["status"] != "ok":
            raise RuntimeError(reranker_status["detail"])
        logger.info("Reranker ready from local path: %s", reranker_status["path"])
    else:
        logger.warning("Reranker disabled by configuration; retrieval quality may drop.")

    metadata_store = get_metadata_store()
    repair_summary = metadata_store.repair_document_records()
    bm25_store = get_bm25_store()
    logger.info(
        "startup_reconciliation",
        extra={
            "document_count": len(metadata_store.list_documents()),
            "chunk_count": metadata_store.chunk_count(),
            "vector_count": vector_store.count(),
            "bm25_size": bm25_store.size(),
            "document_repairs": repair_summary,
        },
    )

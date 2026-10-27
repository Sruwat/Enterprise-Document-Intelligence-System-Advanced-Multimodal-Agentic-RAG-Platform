from fastapi import APIRouter

from app.core.dependencies import (
    get_app_settings,
    get_bm25_store,
    get_embedding_provider,
    get_evaluation_service,
    get_fallback_llm,
    get_aiwana_worker,
    get_huggingface_registry,
    get_metadata_store,
    get_primary_llm,
    get_reranker,
    get_redis_service,
    get_vector_store,
)
from app.services.readiness import LaunchReadinessService

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    settings = get_app_settings()
    metadata_store = get_metadata_store()
    vector_store = get_vector_store()
    bm25_store = get_bm25_store()
    primary_llm = get_primary_llm()
    fallback_llm = get_fallback_llm()
    reranker = get_reranker()
    embedding_provider = get_embedding_provider()
    embedding_status = embedding_provider.status()
    reranker_status = reranker.status()
    postgres_runtime = metadata_store.runtime_status() if hasattr(metadata_store, "runtime_status") else {"status": "unavailable"}
    return {
        "status": "ok",
        "environment": settings.app_env,
        "documents": len(metadata_store.list_documents()),
        "chunks": metadata_store.chunk_count(),
        "vector_count": vector_store.count(),
        "sparse_docs": bm25_store.size(),
        "qdrant": {"status": "ok" if vector_store.is_available() else "error", "location": vector_store.get_active_location()},
        "llm_provider": settings.llm_provider,
        "llm_status": {
            "primary": {"provider": primary_llm.provider_name, "model": primary_llm.model_name, "status": "ok"},
            "fallback": {
                "provider": getattr(fallback_llm, "provider_name", None) if fallback_llm else None,
                "model": getattr(fallback_llm, "model_name", None) if fallback_llm else None,
                "status": "configured" if fallback_llm else "disabled",
            },
        },
        "embedding_model": settings.embedding_model,
        "embedding_model_path": str(settings.embedding_model_path),
        "embedding_status": embedding_status,
        "reranker_model": settings.reranker_model,
        "reranker_model_path": str(settings.reranker_model_path),
        "reranker_status": reranker_status,
        "postgres_runtime": postgres_runtime,
        "postgres_schema": metadata_store.schema_status() if hasattr(metadata_store, "schema_status") else {"status": "unavailable"},
        "migration_status": {"revision": postgres_runtime.get("migration_revision"), "status": "ok" if postgres_runtime.get("migration_revision") else "warning"},
    }


@router.get("/readiness/launch")
def launch_readiness() -> dict:
    settings = get_app_settings()
    return LaunchReadinessService(
        settings=settings,
        metadata_store=get_metadata_store(),
        vector_store=get_vector_store(),
        embedding_provider=get_embedding_provider(),
        reranker=get_reranker(),
        primary_llm=get_primary_llm(),
        redis_service=get_redis_service(),
        evaluation_service=get_evaluation_service(),
        worker=get_aiwana_worker(),
        huggingface_registry=get_huggingface_registry(),
    ).report()


@router.get("/readiness/qdrant")
def qdrant_readiness() -> dict:
    settings = get_app_settings()
    vector_store = get_vector_store()
    vector_size = 1024 if "bge-m3" in settings.embedding_model.lower() else 384
    report = vector_store.verify_collection(vector_size=vector_size)
    report["filter_probe"] = vector_store.verify_server_side_filters(vector_size=vector_size)
    report["ok"] = bool(report.get("ok") and report["filter_probe"].get("ok"))
    return report

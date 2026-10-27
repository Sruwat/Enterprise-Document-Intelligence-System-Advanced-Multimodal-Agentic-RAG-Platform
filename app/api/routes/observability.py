from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth_context import get_current_user
from app.api.rbac import require_permission
from app.core.dependencies import get_aiwana_worker, get_evaluation_service, get_graph_repository, get_huggingface_registry, get_metadata_store, get_primary_llm, get_query_cache, get_redis_service, get_vector_store, get_worker_queue
from app.core.schemas import UserRecord
from app.services.observability import ObservabilityDashboard

router = APIRouter(tags=["observability"])


@router.get("/observability/workspaces/{workspace_id}/snapshot")
def workspace_observability_snapshot(
    workspace_id: str,
    metadata_store=Depends(get_metadata_store),
    vector_store=Depends(get_vector_store),
    redis_service=Depends(get_redis_service),
    graph_repository=Depends(get_graph_repository),
    primary_llm=Depends(get_primary_llm),
    worker=Depends(get_aiwana_worker),
    queue=Depends(get_worker_queue),
    huggingface_registry=Depends(get_huggingface_registry),
    query_cache=Depends(get_query_cache),
    evaluation_service=Depends(get_evaluation_service),
    user: UserRecord = Depends(get_current_user),
):
    require_permission(workspace_id, "workspace.read", user, metadata_store)
    snapshot = ObservabilityDashboard(
        metadata_store,
        vector_store=vector_store,
        redis_service=redis_service,
        graph_repository=graph_repository,
        primary_llm=primary_llm,
        worker=worker,
        queue=queue,
        huggingface_registry=huggingface_registry,
        query_cache=query_cache,
        evaluation_service=evaluation_service,
    ).snapshot()
    snapshot["workspace_id"] = workspace_id
    return snapshot

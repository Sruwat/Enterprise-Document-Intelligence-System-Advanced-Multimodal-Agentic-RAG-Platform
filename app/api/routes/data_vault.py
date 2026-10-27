from __future__ import annotations

from datetime import datetime
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.auth_context import get_current_user
from app.api.rbac import require_permission
from app.core.dependencies import get_app_settings, get_bm25_store, get_graph_repository, get_metadata_store, get_query_cache, get_vector_store
from app.core.schemas import DataFootprintSummary, DataLineage, DataVaultOverview, DeletionRequestRecord, PurgeJobRecord, PurgeRequest, UserRecord
from app.services.data_vault import DataVaultService, DocumentPurgeService, temporary_expiry
from app.services.retention import RetentionPolicyEngine

router = APIRouter(tags=["data-vault"])


class DocumentDataPolicyRequest(BaseModel):
    document_mode: Literal["knowledge_base", "temporary_analysis"] = "knowledge_base"
    temporary_retention: str | None = Field(default=None, description="session, 1h, 24h, 7d, 30d, or ISO timestamp")
    classification: Literal["public", "internal", "confidential", "highly_confidential", "regulated"] = "internal"
    external_processing_allowed: bool | None = None


@router.get("/workspaces/{workspace_id}/data-vault", response_model=DataVaultOverview)
def data_vault_overview(
    workspace_id: str,
    metadata_store=Depends(get_metadata_store),
    vector_store=Depends(get_vector_store),
    graph_repository=Depends(get_graph_repository),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
) -> DataVaultOverview:
    workspace = require_permission(workspace_id, "data_vault.read", user, metadata_store)
    return DataVaultService(metadata_store=metadata_store, vector_store=vector_store, graph_repository=graph_repository, settings=settings).overview(
        workspace_id=workspace_id,
        tenant_id=workspace.tenant_id,
    )


@router.get("/workspaces/{workspace_id}/data-vault/documents/{document_id}", response_model=DataFootprintSummary)
def document_footprint(
    workspace_id: str,
    document_id: str,
    metadata_store=Depends(get_metadata_store),
    vector_store=Depends(get_vector_store),
    graph_repository=Depends(get_graph_repository),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
) -> DataFootprintSummary:
    workspace = require_permission(workspace_id, "data_vault.read", user, metadata_store)
    document = _document_or_404(metadata_store, workspace_id, document_id)
    return DataVaultService(metadata_store=metadata_store, vector_store=vector_store, graph_repository=graph_repository, settings=settings).document_footprint(
        document=document,
        tenant_id=workspace.tenant_id,
    )


@router.get("/workspaces/{workspace_id}/data-vault/documents/{document_id}/lineage", response_model=DataLineage)
def document_lineage(
    workspace_id: str,
    document_id: str,
    metadata_store=Depends(get_metadata_store),
    vector_store=Depends(get_vector_store),
    graph_repository=Depends(get_graph_repository),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
) -> DataLineage:
    workspace = require_permission(workspace_id, "data_vault.inspect_lineage", user, metadata_store)
    document = _document_or_404(metadata_store, workspace_id, document_id)
    return DataVaultService(metadata_store=metadata_store, vector_store=vector_store, graph_repository=graph_repository, settings=settings).lineage(document=document, tenant_id=workspace.tenant_id)


@router.get("/workspaces/{workspace_id}/data-vault/export")
def export_data_vault(
    workspace_id: str,
    metadata_store=Depends(get_metadata_store),
    vector_store=Depends(get_vector_store),
    graph_repository=Depends(get_graph_repository),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
):
    workspace = require_permission(workspace_id, "data_vault.export", user, metadata_store)
    payload = DataVaultService(metadata_store=metadata_store, vector_store=vector_store, graph_repository=graph_repository, settings=settings).export_metadata(workspace_id=workspace_id, tenant_id=workspace.tenant_id)
    metadata_store.add_audit_log("data_vault.export", user=user, workspace_id=workspace_id, resource_type="workspace", resource_id=workspace_id)
    return JSONResponse(content=payload)


@router.get("/workspaces/{workspace_id}/data-vault/documents/{document_id}/access-history")
def document_access_history(workspace_id: str, document_id: str, metadata_store=Depends(get_metadata_store), user: UserRecord = Depends(get_current_user)):
    require_permission(workspace_id, "data_vault.read", user, metadata_store)
    _document_or_404(metadata_store, workspace_id, document_id)
    return [item.model_dump(mode="json") for item in metadata_store.list_audit_logs(workspace_id=workspace_id, limit=500) if item.resource_id == document_id]


@router.post("/workspaces/{workspace_id}/data-vault/documents/{document_id}/purge-request", response_model=DeletionRequestRecord)
def request_document_purge(workspace_id: str, document_id: str, request: PurgeRequest, metadata_store=Depends(get_metadata_store), user: UserRecord = Depends(get_current_user)):
    workspace = require_permission(workspace_id, "documents.request_purge", user, metadata_store)
    document = _document_or_404(metadata_store, workspace_id, document_id)
    request_id = str(uuid.uuid4())
    record = DeletionRequestRecord(request_id=request_id, tenant_id=workspace.tenant_id, workspace_id=workspace_id, document_id=document.document_id, requested_by=user.user_id, reason=request.reason, created_at=datetime.utcnow(), metadata={"filename": document.filename})
    creator = getattr(metadata_store, "create_deletion_request", None)
    if not callable(creator):
        raise HTTPException(status_code=503, detail="Deletion request storage is unavailable.")
    creator(record)
    metadata_store.add_audit_log("data_vault.purge_requested", user=user, workspace_id=workspace_id, resource_type="document", resource_id=document_id, metadata={"request_id": request_id, "reason": request.reason})
    return record


@router.get("/workspaces/{workspace_id}/data-vault/deletion-requests", response_model=list[DeletionRequestRecord])
def deletion_requests(workspace_id: str, metadata_store=Depends(get_metadata_store), user: UserRecord = Depends(get_current_user)):
    require_permission(workspace_id, "deletion_receipts.read", user, metadata_store)
    lister = getattr(metadata_store, "list_deletion_requests", None)
    return lister(workspace_id, limit=100) if callable(lister) else []


@router.post("/workspaces/{workspace_id}/data-vault/deletion-requests/{request_id}/approve", response_model=PurgeJobRecord)
def approve_document_purge(workspace_id: str, request_id: str, metadata_store=Depends(get_metadata_store), vector_store=Depends(get_vector_store), sparse_store=Depends(get_bm25_store), graph_repository=Depends(get_graph_repository), query_cache=Depends(get_query_cache), settings=Depends(get_app_settings), user: UserRecord = Depends(get_current_user)):
    workspace = require_permission(workspace_id, "documents.approve_purge", user, metadata_store)
    getter = getattr(metadata_store, "get_deletion_request", None)
    deletion = getter(request_id, workspace_id) if callable(getter) else None
    if deletion is None or deletion.status not in {"pending", "approved"}:
        raise HTTPException(status_code=404, detail="Deletion request not found or no longer actionable.")
    document = _document_or_404(metadata_store, workspace_id, deletion.document_id)
    updater = getattr(metadata_store, "update_deletion_request", None)
    if callable(updater):
        updater(request_id, status="approved", approved_by=user.user_id)
    job = DocumentPurgeService(metadata_store=metadata_store, vector_store=vector_store, sparse_store=sparse_store, query_cache=query_cache, graph_repository=graph_repository, settings=settings).purge(document=document, tenant_id=workspace.tenant_id, user=user, reason=deletion.reason)
    if callable(updater):
        updater(request_id, status="completed" if job.status == "completed" else "approved", approved_by=user.user_id)
    return job


@router.get("/workspaces/{workspace_id}/data-vault/documents/{document_id}/chunks")
def indexed_chunks(
    workspace_id: str,
    document_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
):
    require_permission(workspace_id, "data_vault.read", user, metadata_store)
    _document_or_404(metadata_store, workspace_id, document_id)
    chunks = metadata_store.list_chunks(document_id=document_id)
    return {
        "document_id": document_id,
        "workspace_id": workspace_id,
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "filename": chunk.filename,
                "page_number": chunk.page_number,
                "chunk_position": chunk.chunk_position,
                "content_type": chunk.content_type,
                "text_preview": chunk.text[:500],
                "embedding_status": "indexed",
                "index_status": "metadata_present",
                "graph_relationship_count": None,
            }
            for chunk in chunks
        ],
    }


@router.patch("/workspaces/{workspace_id}/data-vault/documents/{document_id}/policy", response_model=DataFootprintSummary)
def update_document_data_policy(
    workspace_id: str,
    document_id: str,
    request: DocumentDataPolicyRequest,
    metadata_store=Depends(get_metadata_store),
    vector_store=Depends(get_vector_store),
    graph_repository=Depends(get_graph_repository),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
) -> DataFootprintSummary:
    workspace = require_permission(workspace_id, "retention.manage", user, metadata_store)
    document = _document_or_404(metadata_store, workspace_id, document_id)
    metadata = dict(document.metadata or {})
    metadata["document_mode"] = request.document_mode
    metadata["classification"] = request.classification
    if request.external_processing_allowed is not None:
        metadata["external_processing_allowed"] = request.external_processing_allowed
    policy = RetentionPolicyEngine(settings).resolve(workspace=workspace, document=document)
    if policy.retention_locked and request.temporary_retention and request.temporary_retention != metadata.get("temporary_retention"):
        raise HTTPException(status_code=403, detail="Retention policy is locked for this document.")
    expiry = RetentionPolicyEngine(settings).expiry_for(mode=request.document_mode, retention=request.temporary_retention, policy=policy) if request.document_mode == "temporary_analysis" else None
    metadata["expires_at"] = expiry.isoformat() if expiry else None
    metadata["temporary_retention"] = request.temporary_retention
    metadata["retention_policy"] = policy.as_dict()
    metadata["policy_updated_at"] = datetime.utcnow().isoformat()
    document.metadata = metadata
    document.updated_at = datetime.utcnow()
    metadata_store.upsert_document(document)
    metadata_store.add_audit_log(
        "data_vault.update_document_policy",
        user=user,
        workspace_id=workspace_id,
        resource_type="document",
        resource_id=document_id,
        metadata={"document_mode": request.document_mode, "classification": request.classification, "expires_at": metadata["expires_at"]},
    )
    return DataVaultService(metadata_store=metadata_store, vector_store=vector_store, graph_repository=graph_repository, settings=settings).document_footprint(
        document=document,
        tenant_id=workspace.tenant_id,
    )


@router.post("/workspaces/{workspace_id}/data-vault/documents/{document_id}/purge", response_model=PurgeJobRecord)
def purge_document(
    workspace_id: str,
    document_id: str,
    request: PurgeRequest,
    metadata_store=Depends(get_metadata_store),
    vector_store=Depends(get_vector_store),
    sparse_store=Depends(get_bm25_store),
    graph_repository=Depends(get_graph_repository),
    query_cache=Depends(get_query_cache),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
) -> PurgeJobRecord:
    workspace = require_permission(workspace_id, "data_vault.purge", user, metadata_store)
    document = _document_or_404(metadata_store, workspace_id, document_id)
    return DocumentPurgeService(
        metadata_store=metadata_store,
        vector_store=vector_store,
        sparse_store=sparse_store,
        query_cache=query_cache,
        graph_repository=graph_repository,
        settings=settings,
    ).purge(document=document, tenant_id=workspace.tenant_id, user=user, reason=request.reason)


@router.get("/workspaces/{workspace_id}/data-vault/purge-jobs", response_model=list[PurgeJobRecord])
def purge_jobs(
    workspace_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> list[PurgeJobRecord]:
    require_permission(workspace_id, "data_vault.read", user, metadata_store)
    lister = getattr(metadata_store, "list_purge_jobs", None)
    return lister(workspace_id, limit=100) if callable(lister) else []


def _document_or_404(metadata_store, workspace_id: str, document_id: str):
    document = metadata_store.get_document(document_id, workspace_id=workspace_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document

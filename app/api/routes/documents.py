from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.auth_context import get_current_user
from app.api.rbac import can_access, require_permission
from app.core.dependencies import get_app_settings, get_bm25_store, get_metadata_store, get_query_cache, get_vector_store
from app.core.schemas import UserRecord

router = APIRouter(tags=["documents"])


@router.get("/documents")
def list_documents(
    workspace_id: str | None = None,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
):
    documents = metadata_store.list_documents(workspace_id=workspace_id)
    allowed_workspaces = {
        workspace.workspace_id
        for workspace in metadata_store.list_workspaces()
        if can_access(workspace, user, metadata_store, "workspace.read")
    }
    return [document for document in documents if document.workspace_id in allowed_workspaces]


@router.get("/workspaces/{workspace_id}/documents/{document_id}/pages/{page_number}/preview")
def page_preview(
    workspace_id: str,
    document_id: str,
    page_number: int,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
):
    require_permission(workspace_id, "workspace.read", user, metadata_store)
    document = metadata_store.get_document(document_id, workspace_id=workspace_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    page = next(
        (entry for entry in document.metadata.get("page_asset_refs", []) if entry.get("page_number") == page_number),
        None,
    )
    preview_path = Path(page.get("preview_path")) if page and page.get("preview_path") else None
    if preview_path is None or not preview_path.exists():
        raise HTTPException(status_code=404, detail="Preview is not available for this page.")
    return FileResponse(preview_path)


@router.get("/documents/{document_id}/artifacts")
def document_artifacts(
    document_id: str,
    artifact_type: str | None = None,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
):
    document = metadata_store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    require_permission(document.workspace_id, "workspace.read", user, metadata_store)
    return metadata_store.list_extracted_artifacts(document_id, artifact_type=artifact_type)


@router.get("/evidence/{evidence_id}")
def evidence_lookup(
    evidence_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
):
    anchor = metadata_store.get_evidence_anchor(evidence_id)
    if anchor is not None:
        require_permission(anchor.workspace_id, "workspace.read", user, metadata_store)
        return {
            "evidence_id": anchor.anchor_id,
            "document_id": anchor.document_id,
            "workspace_id": anchor.workspace_id,
            "chunk_id": anchor.chunk_id,
            "artifact_id": anchor.artifact_id,
            "content_type": anchor.anchor_type,
            "snippet": anchor.citation_text[:1000],
            "anchors": [anchor.model_dump(mode="json")],
            "preview_path": anchor.preview_path,
            "crop_path": anchor.crop_path,
            "bbox": anchor.bbox,
        }
    chunk = metadata_store.get_chunk(evidence_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Evidence not found.")
    require_permission(chunk.workspace_id, "workspace.read", user, metadata_store)
    page_assets = chunk.metadata.get("multimodal_assets", {}) if chunk.metadata else {}
    anchors = page_assets.get("source_anchors", []) or page_assets.get("visual_assets", [])
    return {
        "evidence_id": evidence_id,
        "document_id": chunk.document_id,
        "workspace_id": chunk.workspace_id,
        "filename": chunk.filename,
        "page_number": chunk.page_number,
        "content_type": chunk.content_type,
        "snippet": chunk.text[:1000],
        "anchors": anchors,
        "preview_path": page_assets.get("preview_path"),
        "bbox": chunk.bbox,
    }


@router.delete("/workspaces/{workspace_id}/documents/{document_id}", status_code=204)
def delete_document(
    workspace_id: str,
    document_id: str,
    metadata_store=Depends(get_metadata_store),
    vector_store=Depends(get_vector_store),
    sparse_store=Depends(get_bm25_store),
    query_cache=Depends(get_query_cache),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
):
    require_permission(workspace_id, "document.delete", user, metadata_store)
    document = metadata_store.get_document(document_id, workspace_id=workspace_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    chunk_ids = metadata_store.delete_document(document_id, workspace_id)
    vector_store.delete(chunk_ids)
    sparse_store.remove_documents(chunk_ids)
    query_cache.invalidate_workspace(tenant_id=document.tenant_id, workspace_id=workspace_id)
    _delete_managed_file(Path(document.source_path), Path(settings.upload_dir))
    for page in document.metadata.get("page_asset_refs", []):
        preview_path = page.get("preview_path")
        if preview_path:
            _delete_managed_file(Path(preview_path), Path(settings.data_dir) / "previews")
    return None


def _delete_managed_file(path: Path, managed_root: Path) -> None:
    resolved_root = managed_root.resolve()
    resolved_path = path.resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        return
    if resolved_path.exists() and resolved_path.is_file():
        resolved_path.unlink()

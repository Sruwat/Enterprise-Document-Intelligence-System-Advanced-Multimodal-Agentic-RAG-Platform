from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_context import get_current_user
from app.api.rbac import can_access, require_permission
from app.core.dependencies import get_metadata_store
from app.core.schemas import UserRecord, WorkspaceCreateRequest, WorkspaceRecord

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceRecord, status_code=201)
def create_workspace(
    request: WorkspaceCreateRequest,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> WorkspaceRecord:
    return metadata_store.create_workspace(
        request.name,
        owner_id=user.user_id,
        tenant_id=user.tenant_id,
        private_mode=request.private_mode,
        external_ai_allowed=request.external_ai_allowed,
    )


@router.get("", response_model=list[WorkspaceRecord])
def list_workspaces(
    owner_id: str | None = None,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> list[WorkspaceRecord]:
    requested_owner = user.user_id if owner_id and owner_id != user.user_id else owner_id
    workspaces = metadata_store.list_workspaces(owner_id=requested_owner)
    return [workspace for workspace in workspaces if can_access(workspace, user, metadata_store, "workspace.read")]


@router.get("/{workspace_id}", response_model=WorkspaceRecord)
def get_workspace(
    workspace_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> WorkspaceRecord:
    return require_permission(workspace_id, "workspace.read", user, metadata_store)

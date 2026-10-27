from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.api.auth_context import get_current_user
from app.api.rbac import require_permission
from app.core.dependencies import get_metadata_store
from app.core.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyRecord,
    UserRecord,
    WorkspaceInvitationCreateRequest,
    WorkspaceInvitationCreateResponse,
    WorkspaceInvitationRecord,
)
from app.services.auth.api_keys import ApiKeyService
from app.services.auth.invitations import InvitationService

router = APIRouter(tags=["admin"])


class MemberRoleUpdateRequest(BaseModel):
    user_id: str
    role: str


@router.post("/workspaces/{workspace_id}/api-keys", response_model=ApiKeyCreateResponse, status_code=201)
def create_workspace_api_key(
    workspace_id: str,
    request: ApiKeyCreateRequest,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> ApiKeyCreateResponse:
    workspace = require_permission(workspace_id, "workspace.admin", user, metadata_store)
    try:
        response = ApiKeyService(metadata_store).create_key(
            workspace=workspace,
            creator=user,
            name=request.name,
            role=request.role,
            permissions=request.permissions,
            expires_at=request.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata_store.add_audit_log("api_key.create", user=user, workspace_id=workspace_id, resource_type="api_key", resource_id=response.key_id)
    return response


@router.get("/workspaces/{workspace_id}/api-keys", response_model=list[ApiKeyRecord])
def list_workspace_api_keys(
    workspace_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> list[ApiKeyRecord]:
    require_permission(workspace_id, "workspace.admin", user, metadata_store)
    return metadata_store.list_api_keys(workspace_id)


@router.delete("/workspaces/{workspace_id}/api-keys/{key_id}", status_code=204, response_class=Response)
def revoke_workspace_api_key(
    workspace_id: str,
    key_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> Response:
    require_permission(workspace_id, "workspace.admin", user, metadata_store)
    revoked = metadata_store.revoke_api_key(workspace_id, key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found or already revoked.")
    metadata_store.add_audit_log("api_key.revoke", user=user, workspace_id=workspace_id, resource_type="api_key", resource_id=key_id)
    return Response(status_code=204)


@router.post("/workspaces/{workspace_id}/invitations", response_model=WorkspaceInvitationCreateResponse, status_code=201)
def create_workspace_invitation(
    workspace_id: str,
    request: WorkspaceInvitationCreateRequest,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> WorkspaceInvitationCreateResponse:
    workspace = require_permission(workspace_id, "members.invite", user, metadata_store)
    try:
        response = InvitationService(metadata_store).create_invitation(
            workspace=workspace,
            email=request.email,
            role=request.role,
            invited_by=user,
            expires_at=request.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata_store.add_audit_log("invitation.create", user=user, workspace_id=workspace_id, resource_type="workspace_invitation", resource_id=response.invitation_id, metadata={"email": response.email, "role": response.role})
    return response


@router.get("/workspaces/{workspace_id}/invitations", response_model=list[WorkspaceInvitationRecord])
def list_workspace_invitations(
    workspace_id: str,
    include_inactive: bool = False,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> list[WorkspaceInvitationRecord]:
    require_permission(workspace_id, "members.read", user, metadata_store)
    return metadata_store.list_workspace_invitations(workspace_id, include_inactive=include_inactive)


@router.delete("/workspaces/{workspace_id}/invitations/{invitation_id}", status_code=204, response_class=Response)
def revoke_workspace_invitation(
    workspace_id: str,
    invitation_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> Response:
    require_permission(workspace_id, "members.manage", user, metadata_store)
    if not metadata_store.revoke_workspace_invitation(workspace_id, invitation_id):
        raise HTTPException(status_code=404, detail="Invitation not found or already inactive.")
    metadata_store.add_audit_log("invitation.revoke", user=user, workspace_id=workspace_id, resource_type="workspace_invitation", resource_id=invitation_id)
    return Response(status_code=204)


@router.post("/workspaces/{workspace_id}/members/role", status_code=204, response_class=Response)
def update_workspace_member_role(
    workspace_id: str,
    request: MemberRoleUpdateRequest,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> Response:
    require_permission(workspace_id, "members.manage", user, metadata_store)
    try:
        metadata_store.set_workspace_member(workspace_id, request.user_id, request.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata_store.add_audit_log("member.role_change", user=user, workspace_id=workspace_id, resource_type="workspace_member", resource_id=request.user_id, metadata={"role": request.role})
    return Response(status_code=204)

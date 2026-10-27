from __future__ import annotations

from fastapi import HTTPException

from app.api.auth_context import require_workspace_access
from app.core.schemas import UserRecord, WorkspaceRecord


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": {
        "workspace.read",
        "workspace.admin",
        "workspace.manage",
        "members.read",
        "members.invite",
        "members.manage",
        "document.upload",
        "document.query",
        "document.delete",
        "documents.read",
        "documents.upload",
        "documents.delete",
        "chat.query",
        "evidence.read",
        "audit.read",
        "settings.manage",
        "api_keys.read",
        "api_keys.create",
        "api_keys.revoke",
        "data_vault.read",
        "data_vault.purge",
        "retention.manage",
        "data_vault.inspect_lineage",
        "data_vault.export",
        "documents.request_purge",
        "documents.approve_purge",
        "deletion_receipts.read",
    },
    "admin": {
        "workspace.read",
        "workspace.admin",
        "workspace.manage",
        "members.read",
        "members.invite",
        "members.manage",
        "document.upload",
        "document.query",
        "document.delete",
        "documents.read",
        "documents.upload",
        "documents.delete",
        "chat.query",
        "evidence.read",
        "audit.read",
        "settings.manage",
        "api_keys.read",
        "api_keys.create",
        "api_keys.revoke",
        "data_vault.read",
        "data_vault.purge",
        "retention.manage",
        "data_vault.inspect_lineage",
        "data_vault.export",
        "documents.request_purge",
        "documents.approve_purge",
        "deletion_receipts.read",
    },
    "analyst": {
        "workspace.read",
        "members.read",
        "document.upload",
        "document.query",
        "documents.read",
        "documents.upload",
        "chat.query",
        "evidence.read",
        "data_vault.read",
        "data_vault.inspect_lineage",
        "documents.request_purge",
    },
    "member": {
        "workspace.read",
        "documents.read",
        "chat.query",
        "evidence.read",
    },
    "viewer": {
        "workspace.read",
        "document.query",
        "documents.read",
        "chat.query",
        "evidence.read",
    },
    "auditor": {
        "workspace.read",
        "members.read",
        "audit.read",
        "evidence.read",
        "data_vault.read",
        "data_vault.inspect_lineage",
        "data_vault.export",
        "deletion_receipts.read",
    },
}


def workspace_role(workspace: WorkspaceRecord, user: UserRecord, metadata_store) -> str | None:
    api_scope = user.preferences.get("api_key") if isinstance(user.preferences, dict) else None
    if isinstance(api_scope, dict) and api_scope.get("workspace_id") == workspace.workspace_id:
        return str(api_scope.get("role") or "").lower()
    if workspace.owner_id == user.user_id:
        return "owner"
    role_getter = getattr(metadata_store, "get_workspace_member_role", None)
    if callable(role_getter):
        role = role_getter(workspace.workspace_id, user.user_id)
        return str(role).lower() if role else None
    return None


def can_access(workspace: WorkspaceRecord, user: UserRecord, metadata_store, permission: str) -> bool:
    if workspace.tenant_id != user.tenant_id:
        return False
    role = workspace_role(workspace, user, metadata_store)
    api_scope = user.preferences.get("api_key") if isinstance(user.preferences, dict) else None
    if isinstance(api_scope, dict):
        scoped = set(api_scope.get("permissions") or [])
        if scoped:
            return permission in scoped
    if not role:
        return False
    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(workspace_id: str, permission: str, user: UserRecord, metadata_store) -> WorkspaceRecord:
    workspace = require_workspace_access(workspace_id, user, metadata_store)
    role = workspace_role(workspace, user, metadata_store)
    api_scope = user.preferences.get("api_key") if isinstance(user.preferences, dict) else None
    if isinstance(api_scope, dict):
        scoped = set(api_scope.get("permissions") or [])
        if scoped and permission not in scoped:
            raise HTTPException(status_code=403, detail=f"API key permission denied: {permission}")
    if permission not in ROLE_PERMISSIONS.get(role or "", set()):
        raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")
    return workspace

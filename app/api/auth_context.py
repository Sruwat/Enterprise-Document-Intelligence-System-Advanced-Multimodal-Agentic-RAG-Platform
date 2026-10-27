from __future__ import annotations

import hashlib

from fastapi import Cookie, Depends, Header, HTTPException

from app.core.dependencies import get_app_settings, get_metadata_store
from app.core.schemas import UserRecord, WorkspaceRecord
from app.db.base import set_rls_context


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return authorization.strip()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_current_user(
    authorization: str | None = Header(default=None),
    aiwana_session: str | None = Cookie(default=None),
    settings=Depends(get_app_settings),
    metadata_store=Depends(get_metadata_store),
) -> UserRecord:
    token = bearer_token(authorization) or aiwana_session
    if token:
        if token.startswith("aiw_"):
            api_key = metadata_store.get_api_key_by_hash(hash_token(token)) if hasattr(metadata_store, "get_api_key_by_hash") else None
            if api_key and api_key.revoked_at is None:
                workspace = metadata_store.get_workspace(api_key.workspace_id)
                if workspace:
                    metadata_store.mark_api_key_used(api_key.key_id)
                    set_rls_context(workspace.tenant_id, api_key.workspace_id)
                    return UserRecord(
                        user_id=f"api-key:{api_key.key_id}",
                        tenant_id=workspace.tenant_id,
                        email=f"{api_key.key_id}@api-key.aiwana.local",
                        display_name=api_key.name,
                        created_at=api_key.created_at,
                        updated_at=api_key.last_used_at,
                        preferences={
                            "api_key": {
                                "key_id": api_key.key_id,
                                "workspace_id": api_key.workspace_id,
                                "role": api_key.role,
                                "permissions": api_key.permissions,
                            }
                        },
                    )
        user_id = metadata_store.get_user_id_for_session(hash_token(token))
        if user_id:
            user = metadata_store.get_user(user_id)
            if user:
                if user.status != "active":
                    raise HTTPException(status_code=403, detail="User account is disabled or suspended.")
                set_rls_context(user.tenant_id)
                return _redact_user(user)
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    if settings.require_auth or settings.app_env.lower() == "production" or not settings.enable_local_user_fallback:
        raise HTTPException(status_code=401, detail="Authentication required.")
    local_user = metadata_store.get_user("local-user")
    if local_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return _redact_user(local_user)


def require_workspace_access(workspace_id: str, user: UserRecord, metadata_store) -> WorkspaceRecord:
    workspace = metadata_store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Knowledge space not found.")
    if workspace.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Knowledge space does not belong to your tenant.")
    set_rls_context(user.tenant_id, workspace_id)
    api_scope = user.preferences.get("api_key") if isinstance(user.preferences, dict) else None
    if isinstance(api_scope, dict):
        if api_scope.get("workspace_id") != workspace_id:
            raise HTTPException(status_code=403, detail="API key is not scoped to this knowledge space.")
        return workspace
    if workspace.owner_id == user.user_id:
        return workspace
    role_getter = getattr(metadata_store, "get_workspace_member_role", None)
    role = role_getter(workspace_id, user.user_id) if callable(role_getter) else None
    if not role:
        raise HTTPException(status_code=403, detail="You do not have access to this knowledge space.")
    return workspace


def _redact_user(user: UserRecord) -> UserRecord:
    user.preferences = {key: value for key, value in user.preferences.items() if key not in {"password_hash", "password_salt"}}
    return user

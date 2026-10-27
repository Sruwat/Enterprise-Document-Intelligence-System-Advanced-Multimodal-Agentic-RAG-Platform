from __future__ import annotations

import secrets
from datetime import datetime

from app.api.auth_context import hash_token
from app.api.rbac import ROLE_PERMISSIONS
from app.core.schemas import ApiKeyCreateResponse, ApiKeyRecord, UserRecord, WorkspaceRecord


class ApiKeyService:
    PREFIX = "aiw_"

    def __init__(self, metadata_store) -> None:
        self.metadata_store = metadata_store

    def create_key(
        self,
        *,
        workspace: WorkspaceRecord,
        creator: UserRecord,
        name: str,
        role: str,
        permissions: list[str],
        expires_at: datetime | None = None,
    ) -> ApiKeyCreateResponse:
        normalized_role = role.strip().lower()
        if normalized_role not in {"admin", "analyst", "viewer", "auditor"}:
            raise ValueError("API key role must be admin, analyst, viewer, or auditor.")
        allowed = ROLE_PERMISSIONS.get(normalized_role, set())
        scoped_permissions = sorted(set(permissions) & allowed) if permissions else sorted(allowed)
        raw_key = f"{self.PREFIX}{secrets.token_urlsafe(32)}"
        masked = self.mask(raw_key)
        record = self.metadata_store.create_api_key(
            workspace_id=workspace.workspace_id,
            tenant_id=workspace.tenant_id,
            key_hash=hash_token(raw_key),
            name=name,
            masked_key=masked,
            role=normalized_role,
            permissions=scoped_permissions,
            created_by=creator.user_id,
            expires_at=expires_at,
        )
        return ApiKeyCreateResponse(
            key_id=record.key_id,
            api_key=raw_key,
            masked_key=masked,
            name=record.name,
            workspace_id=workspace.workspace_id,
            role=normalized_role,
            permissions=scoped_permissions,
            created_at=record.created_at,
        )

    def authenticate(self, raw_key: str) -> tuple[ApiKeyRecord, UserRecord] | None:
        if not raw_key.startswith(self.PREFIX):
            return None
        record = self.metadata_store.get_api_key_by_hash(hash_token(raw_key))
        if record is None or record.revoked_at is not None:
            return None
        workspace = self.metadata_store.get_workspace(record.workspace_id)
        if workspace is None:
            return None
        self.metadata_store.mark_api_key_used(record.key_id)
        user = UserRecord(
            user_id=f"api-key:{record.key_id}",
            tenant_id=workspace.tenant_id,
            email=f"{record.key_id}@api-key.aiwana.local",
            display_name=record.name,
            created_at=record.created_at,
            updated_at=datetime.utcnow(),
            preferences={
                "api_key": {
                    "key_id": record.key_id,
                    "workspace_id": record.workspace_id,
                    "role": record.role,
                    "permissions": record.permissions,
                }
            },
        )
        return record, user

    @staticmethod
    def mask(raw_key: str) -> str:
        return f"{raw_key[:8]}...{raw_key[-6:]}"

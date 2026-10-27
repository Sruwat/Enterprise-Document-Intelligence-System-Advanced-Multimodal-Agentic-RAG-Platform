from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth_context import get_current_user
from app.api.rbac import require_permission
from app.core.dependencies import get_metadata_store
from app.core.schemas import AuditLogRecord, UserRecord

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=list[AuditLogRecord])
def list_audit_logs(
    workspace_id: str | None = None,
    limit: int = 100,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> list[AuditLogRecord]:
    if workspace_id:
        require_permission(workspace_id, "audit.read", user, metadata_store)
        return metadata_store.list_audit_logs(tenant_id=user.tenant_id, workspace_id=workspace_id, limit=min(limit, 200))
    return metadata_store.list_audit_logs(tenant_id=user.tenant_id, limit=min(limit, 200))

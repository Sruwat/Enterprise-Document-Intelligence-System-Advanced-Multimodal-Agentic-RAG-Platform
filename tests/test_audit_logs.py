from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_context import hash_token
from app.api.routes.audit import router as audit_router
from app.core.dependencies import get_metadata_store
from app.storage.metadata_store import MetadataStore


def test_audit_logs_route_is_reachable_and_tenant_scoped(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    tenant_a = store.create_user("a@example.com", tenant_id="tenant-a")
    tenant_b = store.create_user("b@example.com", tenant_id="tenant-b")
    store.create_workspace("Tenant A", owner_id=tenant_a.user_id, tenant_id=tenant_a.tenant_id)
    workspace_b = store.create_workspace("Tenant B", owner_id=tenant_b.user_id, tenant_id=tenant_b.tenant_id)
    store.create_auth_session(hash_token("token-a"), tenant_a.user_id, datetime.utcnow().replace(year=2099))
    store.add_audit_log("tenant-a.event", user=tenant_a, workspace_id="default")
    store.add_audit_log("tenant-b.event", user=tenant_b, workspace_id=workspace_b.workspace_id)
    app = FastAPI()
    app.include_router(audit_router)
    app.dependency_overrides[get_metadata_store] = lambda: store

    with TestClient(app) as client:
        response = client.get("/audit/logs", headers={"Authorization": "Bearer token-a"})
        forbidden = client.get(f"/audit/logs?workspace_id={workspace_b.workspace_id}", headers={"Authorization": "Bearer token-a"})

    assert response.status_code == 200
    assert [item["event_type"] for item in response.json()] == ["tenant-a.event"]
    assert forbidden.status_code == 403

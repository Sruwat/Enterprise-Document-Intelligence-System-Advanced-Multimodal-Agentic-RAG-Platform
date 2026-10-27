from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_context import hash_token
from app.api.routes.admin import router as admin_router
from app.api.routes.workspaces import router as workspaces_router
from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_metadata_store
from app.storage.metadata_store import MetadataStore


def _app(store, settings):
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(workspaces_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: settings
    return app


def test_workspace_api_key_create_list_revoke_and_auth(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    settings = Settings(REQUIRE_AUTH=True, ENABLE_LOCAL_USER_FALLBACK=False, DATABASE_BACKEND="sqlite", METADATA_DB=str(tmp_path / "metadata.db"))
    owner = store.create_user("owner@example.com", tenant_id="tenant-a")
    workspace = store.create_workspace("Admin", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    token = "owner-token"
    store.create_auth_session(hash_token(token), owner.user_id, datetime.utcnow().replace(year=2099))

    with TestClient(_app(store, settings)) as client:
        created = client.post(
            f"/workspaces/{workspace.workspace_id}/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "CI", "role": "viewer", "permissions": ["workspace.read", "document.query"]},
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["api_key"].startswith("aiw_")
        assert payload["masked_key"].startswith("aiw_")

        listed = client.get(f"/workspaces/{workspace.workspace_id}/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert listed.status_code == 200
        assert listed.json()[0]["masked_key"] == payload["masked_key"]
        assert "api_key" not in listed.json()[0]

        api_read = client.get(f"/workspaces/{workspace.workspace_id}", headers={"Authorization": f"Bearer {payload['api_key']}"})
        assert api_read.status_code == 200

        revoked = client.delete(f"/workspaces/{workspace.workspace_id}/api-keys/{payload['key_id']}", headers={"Authorization": f"Bearer {token}"})
        assert revoked.status_code == 204
        denied = client.get(f"/workspaces/{workspace.workspace_id}", headers={"Authorization": f"Bearer {payload['api_key']}"})
        assert denied.status_code == 401

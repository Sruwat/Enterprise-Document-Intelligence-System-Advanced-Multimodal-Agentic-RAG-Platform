from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.auth import router as auth_router
from app.api.routes.workspaces import router as workspace_router
from app.core.dependencies import get_metadata_store
from app.storage.metadata_store import MetadataStore


def _app(store: MetadataStore) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(workspace_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    return app


def test_signup_login_me_uses_persistent_session(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    app = _app(store)
    with TestClient(app) as client:
        signup = client.post(
            "/auth/signup",
            json={"email": "founder@example.com", "password": "strong-password", "display_name": "Founder"},
        )
        assert signup.status_code == 201
        token = signup.json()["session_token"]
        assert store.get_user_id_for_session(store_token_hash(token)) is not None

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == "founder@example.com"
        assert "password_hash" not in me.json()["preferences"]
        workspaces = client.get("/workspaces", headers={"Authorization": f"Bearer {token}"})
        assert workspaces.status_code == 200
        assert len(workspaces.json()) == 1
        assert workspaces.json()[0]["owner_id"] == signup.json()["user"]["user_id"]

        logout = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert logout.status_code == 200
        expired = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert expired.status_code == 401


def test_workspace_list_scopes_to_authenticated_tenant(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    first = store.create_user("first@example.com", tenant_id="tenant-a")
    second = store.create_user("second@example.com", tenant_id="tenant-b")
    store.create_workspace("Tenant A", owner_id=first.user_id, tenant_id=first.tenant_id)
    store.create_workspace("Tenant B", owner_id=second.user_id, tenant_id=second.tenant_id)
    token = "tenant-a-token"
    store.create_auth_session(store_token_hash(token), first.user_id, datetime.utcnow().replace(year=2099))
    app = _app(store)

    with TestClient(app) as client:
        response = client.get("/workspaces", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    names = {workspace["name"] for workspace in response.json()}
    assert "Tenant A" in names
    assert "Tenant B" not in names


def test_workspace_access_requires_owner_or_member_even_inside_same_tenant(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    owner = store.create_user("owner@example.com", tenant_id="tenant-a")
    outsider = store.create_user("outsider@example.com", tenant_id="tenant-a")
    workspace = store.create_workspace("Private Workspace", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    token = "outsider-token"
    store.create_auth_session(store_token_hash(token), outsider.user_id, datetime.utcnow().replace(year=2099))
    app = _app(store)

    with TestClient(app) as client:
        denied = client.get(f"/workspaces/{workspace.workspace_id}", headers={"Authorization": f"Bearer {token}"})
        listed = client.get("/workspaces", headers={"Authorization": f"Bearer {token}"})

    assert denied.status_code == 403
    assert listed.status_code == 200
    assert listed.json() == []


def test_workspace_member_can_read_when_assigned_role(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    owner = store.create_user("owner@example.com", tenant_id="tenant-a")
    viewer = store.create_user("viewer@example.com", tenant_id="tenant-a")
    workspace = store.create_workspace("Shared Workspace", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    store.set_workspace_member(workspace.workspace_id, viewer.user_id, "viewer")
    token = "viewer-token"
    store.create_auth_session(store_token_hash(token), viewer.user_id, datetime.utcnow().replace(year=2099))
    app = _app(store)

    with TestClient(app) as client:
        response = client.get(f"/workspaces/{workspace.workspace_id}", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["name"] == "Shared Workspace"


def test_email_verification_and_password_reset_tokens_are_single_use(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    app = _app(store)
    with TestClient(app) as client:
        client.post(
            "/auth/signup",
            json={"email": "reset@example.com", "password": "old-password", "display_name": "Reset User"},
        )
        verify_token = client.post("/auth/verify-email/request", json={"email": "reset@example.com"}).json()["token"]
        confirmed = client.post("/auth/verify-email/confirm", json={"token": verify_token})
        reused = client.post("/auth/verify-email/confirm", json={"token": verify_token})
        reset_token = client.post("/auth/password-reset/request", json={"email": "reset@example.com"}).json()["token"]
        reset = client.post("/auth/password-reset/confirm", json={"token": reset_token, "new_password": "new-password"})
        login = client.post("/auth/login", json={"email": "reset@example.com", "password": "new-password"})

    assert confirmed.status_code == 200
    assert reused.status_code == 400
    assert reset.status_code == 200
    assert login.status_code == 200
    assert store.get_user_by_email("reset@example.com").preferences["email_verified"] is True


def store_token_hash(token: str) -> str:
    from app.api.auth_context import hash_token

    return hash_token(token)

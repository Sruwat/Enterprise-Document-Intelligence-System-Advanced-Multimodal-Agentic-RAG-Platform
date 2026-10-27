from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_context import hash_token
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_metadata_store
from app.services.auth.google import GoogleAuthService
from app.services.llm.llm_provider import build_llm_providers
from app.services.redis_client import RedisService
from app.storage.metadata_store import MetadataStore


def _app(store: MetadataStore, settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: settings
    return app


def _session(store: MetadataStore, user_id: str, token: str = "session-token") -> str:
    store.create_auth_session(hash_token(token), user_id, datetime.utcnow() + timedelta(hours=1))
    return token


def test_google_login_accepts_only_invited_email(tmp_path):
    settings = Settings(
        APP_ENV="development",
        AUTH_SECRET="test-secret",
        GOOGLE_CLIENT_ID="google-client",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )
    store = MetadataStore(settings.metadata_db)
    owner = store.create_user("owner@example.com", tenant_id="tenant-a")
    workspace = store.create_workspace("Tenant A", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    owner_token = _session(store, owner.user_id, "owner-token")
    app = _app(store, settings)

    with TestClient(app) as client:
        invite = client.post(
            f"/workspaces/{workspace.workspace_id}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"email": "analyst@example.com", "role": "analyst"},
        )
        assert invite.status_code == 201

        google = GoogleAuthService(settings)
        state = google._sign_payload({"workspace_id": workspace.workspace_id}, purpose="oauth-state")
        identity = google._sign_payload(
            {"email": "analyst@example.com", "sub": "google-subject", "name": "Analyst", "email_verified": True},
            purpose="dev-google-id",
        )
        accepted = client.post("/auth/google/callback", json={"state": state, "id_token": identity})

        wrong_identity = google._sign_payload(
            {"email": "outsider@example.com", "sub": "google-outsider", "name": "Outsider", "email_verified": True},
            purpose="dev-google-id",
        )
        denied = client.post("/auth/google/callback", json={"state": state, "id_token": wrong_identity})

    assert accepted.status_code == 200
    assert accepted.json()["user"]["email"] == "analyst@example.com"
    assert store.get_workspace_member_role(workspace.workspace_id, accepted.json()["user"]["user_id"]) == "analyst"
    assert denied.status_code == 403


def test_disabled_user_session_is_rejected(tmp_path):
    settings = Settings(DATA_DIR=str(tmp_path), UPLOAD_DIR=str(tmp_path / "uploads"), LOG_DIR=str(tmp_path / "logs"), METADATA_DB=str(tmp_path / "metadata.db"))
    store = MetadataStore(settings.metadata_db)
    user = store.create_user("disabled@example.com")
    store.update_user_status(user.user_id, "disabled")
    token = _session(store, user.user_id)
    app = _app(store, settings)

    with TestClient(app) as client:
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_expired_api_key_is_rejected(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    owner = store.create_user("owner@example.com")
    workspace = store.create_workspace("Workspace", owner_id=owner.user_id, tenant_id=owner.tenant_id)
    raw = "aiw_expired"
    store.create_api_key(
        workspace_id=workspace.workspace_id,
        tenant_id=workspace.tenant_id,
        key_hash=hash_token(raw),
        name="Expired",
        masked_key="aiw_...expired",
        role="viewer",
        permissions=["workspace.read"],
        created_by=owner.user_id,
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    )

    assert store.get_api_key_by_hash(hash_token(raw)) is None


def test_private_only_llm_blocks_public_provider(tmp_path):
    settings = Settings(
        LLM_PRIVACY_MODE="private_only",
        LLM_PROVIDER="groq",
        GROQ_API_KEY="test-key",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )

    with pytest.raises(RuntimeError, match="private_only"):
        build_llm_providers(settings)


def test_redis_tenant_keys_are_scoped_even_without_live_redis():
    service = RedisService("redis://localhost:6379/0", enabled=False)

    assert service.tenant_key("tenant-a", "workspace-a", "cache", "abc") != service.tenant_key("tenant-b", "workspace-a", "cache", "abc")
    assert service.tenant_key("tenant-a", "workspace-a", "cache", "abc") != service.tenant_key("tenant-a", "workspace-b", "cache", "abc")


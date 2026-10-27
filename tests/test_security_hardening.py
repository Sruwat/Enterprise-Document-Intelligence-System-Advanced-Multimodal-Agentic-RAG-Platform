from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.auth import router as auth_router
from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_email_sender, get_metadata_store
from app.services.email import EmailSender
from app.storage.metadata_store import MetadataStore


def test_auth_action_tokens_are_not_returned_in_production(tmp_path):
    settings = Settings(
        APP_ENV="production",
        REQUIRE_AUTH=True,
        EMAIL_PROVIDER="smtp",
        SMTP_HOST="smtp.example.test",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )
    store = MetadataStore(settings.metadata_db)
    sender = EmailSender(Settings(DATA_DIR=str(tmp_path), UPLOAD_DIR=str(tmp_path / "uploads"), LOG_DIR=str(tmp_path / "logs"), METADATA_DB=str(tmp_path / "metadata.db")))
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_email_sender] = lambda: sender

    with TestClient(app) as client:
        client.post("/auth/signup", json={"email": "prod@example.com", "password": "safe-password", "display_name": "Prod"})
        response = client.post("/auth/password-reset/request", json={"email": "prod@example.com"})

    assert response.status_code == 200
    assert response.json()["token"] is None
    assert sender.sent_messages


def test_signup_rejects_obviously_weak_password(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_metadata_store] = lambda: store

    with TestClient(app) as client:
        response = client.post("/auth/signup", json={"email": "weak@example.com", "password": "password", "display_name": "Weak"})

    assert response.status_code == 422

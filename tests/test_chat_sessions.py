from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.query import router as query_router
from app.api.routes.workspaces import router as workspace_router
from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_metadata_store
from app.storage.metadata_store import MetadataStore


def test_chat_sessions_can_be_listed_and_reopened(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    app = FastAPI()
    app.include_router(workspace_router)
    app.include_router(query_router)
    app.dependency_overrides[get_metadata_store] = lambda: store
    app.dependency_overrides[get_app_settings] = lambda: Settings(
        REQUIRE_AUTH=False,
        ENABLE_LOCAL_USER_FALLBACK=True,
        DATABASE_BACKEND="sqlite",
        METADATA_DB=str(tmp_path / "metadata.db"),
    )

    with TestClient(app) as client:
        workspace = client.post("/workspaces", json={"name": "Memory"}).json()
        created = client.post(
            "/chat/sessions",
            json={"workspace_id": workspace["workspace_id"], "objective_profile": "legal", "analysis_mode": "agentic"},
        ).json()
        store.add_chat_message(created["session_id"], workspace["workspace_id"], "user", "What is the termination clause?")
        store.add_chat_message(created["session_id"], workspace["workspace_id"], "assistant", "Termination requires notice.")

        sessions = client.get(f"/workspaces/{workspace['workspace_id']}/chat/sessions")
        messages = client.get(f"/chat/sessions/{created['session_id']}/messages")

    assert sessions.status_code == 200
    assert sessions.json()[0]["session_id"] == created["session_id"]
    assert sessions.json()[0]["title"] == "What is the termination clause?"
    assert messages.status_code == 200
    assert [message["role"] for message in messages.json()] == ["user", "assistant"]
    assert messages.json()[0]["content"] == "What is the termination clause?"

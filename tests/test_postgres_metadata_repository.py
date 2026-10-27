from datetime import datetime

from app.core.schemas import ChunkRecord, DocumentRecord, MemoryRecord
from app.core.config import Settings
from app.core import dependencies
from app.db.repositories.postgres_metadata import PostgresMetadataRepository
from app.storage.metadata_store import MetadataStore


def test_postgres_repository_matches_core_metadata_store_contract(tmp_path):
    repo = PostgresMetadataRepository(f"sqlite:///{tmp_path / 'metadata-postgres-contract.db'}")

    user = repo.create_user(
        "founder@example.com",
        display_name="Founder",
        tenant_id="tenant-a",
        preferences={"password_hash": "hash", "password_salt": "salt", "email_verified": False},
    )
    workspace = repo.create_workspace("Tenant A Space", owner_id=user.user_id, tenant_id=user.tenant_id)
    session = repo.create_chat_session(workspace.workspace_id, objective_profile="legal", analysis_mode="agentic")
    repo.add_chat_message(session.session_id, workspace.workspace_id, "user", "What is the termination clause?")
    repo.add_chat_message(session.session_id, workspace.workspace_id, "assistant", "Termination requires notice.")

    repo.create_auth_session("token-hash", user.user_id, datetime.utcnow().replace(year=2099))
    repo.update_user_preferences(user.user_id, {"email_verified": True})

    document = DocumentRecord(
        document_id="doc-1",
        workspace_id=workspace.workspace_id,
        filename="contract.pdf",
        source_path=str(tmp_path / "contract.pdf"),
        fingerprint="fp-1",
        status="indexed",
        page_count=1,
        ingested_at=datetime.utcnow(),
        metadata={},
    )
    repo.upsert_document(document)
    repo.insert_chunks([
        ChunkRecord(
            chunk_id="chunk-1",
            document_id=document.document_id,
            workspace_id=workspace.workspace_id,
            filename=document.filename,
            page_number=1,
            text="Termination requires thirty days notice.",
            token_count=6,
        )
    ])
    repo.upsert_memory(
        MemoryRecord(
            memory_id="memory-1",
            session_id=session.session_id,
            workspace_id=workspace.workspace_id,
            user_id=user.user_id,
            objective_profile="legal",
            memory_type="long_term",
            content="User cares about termination risk.",
            entities=["Termination"],
            created_at=datetime.utcnow(),
        )
    )

    assert repo.get_user_id_for_session("token-hash") == user.user_id
    assert repo.get_user_by_email("founder@example.com").preferences["email_verified"] is True
    assert repo.list_workspaces(owner_id=user.user_id)[0].workspace_id == workspace.workspace_id
    assert repo.list_chat_sessions(workspace.workspace_id)[0].title == "What is the termination clause?"
    assert [message.role for message in repo.list_chat_messages(session.session_id)] == ["user", "assistant"]
    assert repo.get_document_by_fingerprint("fp-1", workspace.workspace_id).document_id == "doc-1"
    assert repo.get_chunks(["chunk-1"], workspace_id=workspace.workspace_id)[0].text.startswith("Termination")
    assert repo.list_memory(session.session_id)[0].entities == ["Termination"]
    assert repo.table_counts()["chunks"] == 1


def test_metadata_store_dependency_switches_between_sqlite_and_postgres(monkeypatch, tmp_path):
    dependencies.get_metadata_store.cache_clear()
    sqlite_settings = Settings(
        DATABASE_BACKEND="sqlite",
        METADATA_DB=str(tmp_path / "sqlite.db"),
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: sqlite_settings)

    assert isinstance(dependencies.get_metadata_store(), MetadataStore)

    dependencies.get_metadata_store.cache_clear()
    postgres_settings = Settings(
        DATABASE_BACKEND="postgres",
        DATABASE_URL=f"sqlite:///{tmp_path / 'postgres-contract.db'}",
        METADATA_DB=str(tmp_path / "ignored-sqlite.db"),
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: postgres_settings)

    assert isinstance(dependencies.get_metadata_store(), PostgresMetadataRepository)
    dependencies.get_metadata_store.cache_clear()

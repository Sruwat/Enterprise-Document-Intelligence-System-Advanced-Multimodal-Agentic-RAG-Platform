from datetime import datetime

from app.core.schemas import (
    AgentRun,
    AgentStep,
    ChunkRecord,
    DocumentRecord,
    EvidenceAnchorRecord,
    ExtractedArtifact,
    IngestionJobRecord,
    MemoryRecord,
)
from app.db.base import Base, build_engine
from app.storage.metadata_store import MetadataStore
from tools.migrate_sqlite_to_postgres import (
    _apply,
    _expected_target_counts,
    _read_sqlite,
    _target_counts,
    _validate_counts,
)


def test_sqlite_to_postgres_migration_applies_and_validates_counts(tmp_path):
    source_db = tmp_path / "metadata.db"
    target_url = f"sqlite:///{tmp_path / 'target.db'}"
    store = MetadataStore(source_db)
    workspace = store.create_workspace("Migration Space")
    user = store.create_user("migration@example.com", preferences={"email_verified": True, "password_hash": "hash", "password_salt": "salt"})
    session = store.create_chat_session(workspace.workspace_id, None, "english", "normal", "legal", "agentic")
    store.add_chat_message(session.session_id, workspace.workspace_id, "user", "What is the termination risk?", {"language": "english"})
    store.add_chat_message(session.session_id, workspace.workspace_id, "assistant", "Termination requires notice.", {"language": "english"})
    store.create_auth_session("session-token-hash", user.user_id, datetime.utcnow().replace(year=2099))
    store.create_auth_action_token("action-token-hash", user.user_id, "email_verification", datetime.utcnow().replace(year=2099))

    document = DocumentRecord(
        document_id="doc-1",
        workspace_id=workspace.workspace_id,
        filename="contract.pdf",
        source_path=str(tmp_path / "contract.pdf"),
        fingerprint="fp-1",
        status="indexed",
        page_count=1,
        ingested_at=datetime.utcnow(),
        metadata={"source": "test"},
    )
    store.upsert_document(document)
    store.insert_chunks([
        ChunkRecord(
            chunk_id="chunk-1",
            document_id=document.document_id,
            workspace_id=workspace.workspace_id,
            filename=document.filename,
            page_number=1,
            text="Termination requires thirty days notice.",
            token_count=6,
            content_type="text",
        )
    ])
    store.upsert_ingestion_job(
        IngestionJobRecord(
            job_id="job-1",
            workspace_id=workspace.workspace_id,
            filename=document.filename,
            status="ready",
            progress=100,
            document_id=document.document_id,
            created_at=datetime.utcnow(),
            metadata={"stage": "done"},
        )
    )
    store.upsert_memory(
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
    store.upsert_extracted_artifact(
        ExtractedArtifact(
            artifact_id="artifact-1",
            document_id=document.document_id,
            workspace_id=workspace.workspace_id,
            artifact_type="clause",
            page_number=1,
            title="Termination",
            text="Thirty days notice.",
            data={"risk": "medium"},
            bbox=[0.1, 0.1, 0.8, 0.2],
            created_at=datetime.utcnow(),
        )
    )
    store.upsert_evidence_anchor(
        EvidenceAnchorRecord(
            anchor_id="anchor-1",
            document_id=document.document_id,
            workspace_id=workspace.workspace_id,
            chunk_id="chunk-1",
            artifact_id="artifact-1",
            anchor_type="clause",
            page_number=1,
            citation_text="contract.pdf p.1",
            created_at=datetime.utcnow(),
        )
    )
    store.log_agent_run(
        AgentRun(
            run_id="run-1",
            session_id=session.session_id,
            workspace_id=workspace.workspace_id,
            objective_profile="legal",
            analysis_mode="agentic",
            steps=[
                AgentStep(
                    step_id="step-1",
                    agent_name="LegalAgent",
                    action="extract_obligations",
                    output_summary="Found termination obligation.",
                )
            ],
            created_at=datetime.utcnow(),
        )
    )
    store.add_audit_log("migration.test", user=user, workspace_id=workspace.workspace_id, resource_type="document", resource_id=document.document_id)
    store.log_query("query-1", {"workspace_id": workspace.workspace_id, "session_id": session.session_id, "question": "termination?"})
    store.log_evaluation_run("eval-1", {"workspace_id": workspace.workspace_id, "metrics": {"citation_coverage": 1.0}})

    source = _read_sqlite(source_db)
    expected = _expected_target_counts(source)
    engine = build_engine(target_url)
    Base.metadata.create_all(engine)

    first_apply = _apply(engine, source)
    first_counts = _target_counts(engine)
    assert _validate_counts(expected, first_counts) == {"ok": True, "mismatches": []}
    assert first_apply["agent_steps"] == 1
    assert first_counts["agent_steps"] == 1

    second_apply = _apply(engine, source)
    second_counts = _target_counts(engine)
    assert second_apply == first_apply
    assert second_counts == first_counts

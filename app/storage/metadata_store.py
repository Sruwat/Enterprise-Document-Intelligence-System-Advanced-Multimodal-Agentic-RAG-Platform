from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.schemas import (
    AgentRun,
    ApiKeyRecord,
    AuditLogRecord,
    ChatMessageRecord,
    ChatSessionRecord,
    ChunkRecord,
    DocumentRecord,
    ExtractedArtifact,
    EvidenceAnchorRecord,
    IngestionJobRecord,
    MemoryRecord,
    PurgeJobRecord,
    DeletionRequestRecord,
    TenantRecord,
    UserRecord,
    WorkspaceInvitationRecord,
    WorkspaceRecord,
)


class MetadataStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    filename TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    fingerprint TEXT,
                    status TEXT NOT NULL DEFAULT 'processing',
                    page_count INTEGER NOT NULL,
                    ingested_at TEXT NOT NULL,
                    updated_at TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    filename TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    section TEXT,
                    token_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS query_logs (
                    query_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deletion_requests (
                    request_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approved_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT 'default-tenant',
                    private_mode INTEGER NOT NULL DEFAULT 0,
                    external_ai_allowed INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspace_members (
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    joined_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS workspace_invitations (
                    invitation_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL,
                    invited_by TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    accepted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    job_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    document_id TEXT,
                    message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    title TEXT,
                    language TEXT NOT NULL,
                    explanation_level TEXT NOT NULL,
                    objective_profile TEXT NOT NULL DEFAULT 'general',
                    analysis_mode TEXT NOT NULL DEFAULT 'quick',
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'free',
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default-tenant',
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    avatar_url TEXT,
                    auth_provider TEXT NOT NULL DEFAULT 'local',
                    provider_subject TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    last_login_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    preferences_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_action_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    masked_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    expires_at TEXT,
                    last_used_at TEXT,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL DEFAULT 'local-user',
                    objective_profile TEXT NOT NULL DEFAULT 'general',
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS extracted_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    artifact_type TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    title TEXT,
                    text TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    bbox_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence_anchors (
                    anchor_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    chunk_id TEXT,
                    artifact_id TEXT,
                    anchor_type TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    bbox_json TEXT,
                    preview_path TEXT,
                    crop_path TEXT,
                    citation_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    objective_profile TEXT NOT NULL DEFAULT 'general',
                    analysis_mode TEXT NOT NULL DEFAULT 'quick',
                    steps_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default-tenant',
                    workspace_id TEXT,
                    user_id TEXT NOT NULL DEFAULT 'local-user',
                    event_type TEXT NOT NULL,
                    actor_email TEXT,
                    resource_type TEXT,
                    resource_id TEXT,
                    status TEXT NOT NULL,
                    message TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS purge_jobs (
                    purge_job_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
            if "fingerprint" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN fingerprint TEXT")
            if "status" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN status TEXT NOT NULL DEFAULT 'processing'")
            if "updated_at" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN updated_at TEXT")
            if "workspace_id" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")
            workspace_columns = {row["name"] for row in conn.execute("PRAGMA table_info(workspaces)").fetchall()}
            if "tenant_id" not in workspace_columns:
                conn.execute("ALTER TABLE workspaces ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default-tenant'")
            member_columns = {row["name"] for row in conn.execute("PRAGMA table_info(workspace_members)").fetchall()}
            if "status" not in member_columns:
                conn.execute("ALTER TABLE workspace_members ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            if "joined_at" not in member_columns:
                conn.execute("ALTER TABLE workspace_members ADD COLUMN joined_at TEXT")
            user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            for name, ddl in {
                "avatar_url": "ALTER TABLE users ADD COLUMN avatar_url TEXT",
                "auth_provider": "ALTER TABLE users ADD COLUMN auth_provider TEXT NOT NULL DEFAULT 'local'",
                "provider_subject": "ALTER TABLE users ADD COLUMN provider_subject TEXT",
                "status": "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
                "last_login_at": "ALTER TABLE users ADD COLUMN last_login_at TEXT",
            }.items():
                if name not in user_columns:
                    conn.execute(ddl)
            api_columns = {row["name"] for row in conn.execute("PRAGMA table_info(api_keys)").fetchall()}
            if "expires_at" not in api_columns:
                conn.execute("ALTER TABLE api_keys ADD COLUMN expires_at TEXT")
            session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
            if "objective_profile" not in session_columns:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN objective_profile TEXT NOT NULL DEFAULT 'general'")
            if "analysis_mode" not in session_columns:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN analysis_mode TEXT NOT NULL DEFAULT 'quick'")
            if "input_language" not in session_columns:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN input_language TEXT NOT NULL DEFAULT 'auto'")
            if "response_language" not in session_columns:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN response_language TEXT NOT NULL DEFAULT 'auto'")
            chunk_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
            if "workspace_id" not in chunk_columns:
                conn.execute("ALTER TABLE chunks ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_fingerprint ON documents(fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members(user_id, role)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workspace_invitations_lookup ON workspace_invitations(workspace_id, email, status, expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workspace_invitations_token ON workspace_invitations(token_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_provider_subject ON users(auth_provider, provider_subject)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks(workspace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_workspace ON ingestion_jobs(workspace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_action_tokens_user ON auth_action_tokens(user_id, action, expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_workspace ON api_keys(workspace_id, revoked_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_records(session_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_workspace ON memory_records(workspace_id, objective_profile)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_document ON extracted_artifacts(document_id, artifact_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_anchors_document ON evidence_anchors(document_id, page_number)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_anchors_workspace ON evidence_anchors(workspace_id, anchor_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_anchors_chunk ON evidence_anchors(chunk_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_created ON audit_logs(tenant_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_workspace_created ON audit_logs(workspace_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_purge_jobs_workspace ON purge_jobs(workspace_id, document_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_deletion_requests_workspace ON deletion_requests(workspace_id, status, created_at)")
            self._ensure_default_workspace(conn)

    def table_names(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    @staticmethod
    def _ensure_default_workspace(conn: sqlite3.Connection) -> None:
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO tenants(tenant_id, name, plan, created_at, updated_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("default-tenant", "Default Tenant", "free", now, now, "{}"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO users(user_id, tenant_id, email, display_name, created_at, updated_at, preferences_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("local-user", "default-tenant", "local@aiwana.dev", "Local User", now, now, "{}"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO workspaces(
                workspace_id, name, owner_id, tenant_id, private_mode, external_ai_allowed, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("default", "Default Knowledge Space", "local-user", "default-tenant", 0, 1, now, now, "{}"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO workspace_members(workspace_id, user_id, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("default", "local-user", "owner", now, now),
        )

    def create_workspace(
        self,
        name: str,
        owner_id: str = "local-user",
        tenant_id: str = "default-tenant",
        private_mode: bool = False,
        external_ai_allowed: bool = True,
    ) -> WorkspaceRecord:
        now = datetime.utcnow()
        record = WorkspaceRecord(
            workspace_id=str(uuid.uuid4()),
            name=name.strip() or "My Knowledge Space",
            owner_id=owner_id,
            tenant_id=tenant_id,
            private_mode=private_mode,
            external_ai_allowed=external_ai_allowed and not private_mode,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspaces(workspace_id, name, owner_id, tenant_id, private_mode, external_ai_allowed, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.workspace_id,
                    record.name,
                    record.owner_id,
                    record.tenant_id,
                    int(record.private_mode),
                    int(record.external_ai_allowed),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    json.dumps(record.metadata),
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO workspace_members(workspace_id, user_id, role, status, joined_at, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
                """,
                (record.workspace_id, record.owner_id, "owner", record.created_at.isoformat(), record.created_at.isoformat(), record.updated_at.isoformat()),
            )
        return record

    def set_workspace_member(self, workspace_id: str, user_id: str, role: str) -> None:
        now = datetime.utcnow().isoformat()
        normalized = role.strip().lower()
        if normalized not in {"owner", "admin", "analyst", "viewer"}:
            raise ValueError(f"Unsupported workspace role: {role}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspace_members(workspace_id, user_id, role, status, joined_at, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(workspace_id, user_id) DO UPDATE SET role = excluded.role, status = 'active', updated_at = excluded.updated_at
                """,
                (workspace_id, user_id, normalized, now, now, now),
            )

    def get_workspace_member_role(self, workspace_id: str, user_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ? AND status = 'active'",
                (workspace_id, user_id),
            ).fetchone()
        return row["role"] if row else None

    def create_api_key(
        self,
        *,
        workspace_id: str,
        tenant_id: str,
        key_hash: str,
        name: str,
        masked_key: str,
        role: str,
        permissions: list[str],
        created_by: str,
        expires_at: datetime | None = None,
    ) -> ApiKeyRecord:
        now = datetime.utcnow()
        key_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys(key_id, workspace_id, tenant_id, key_hash, name, masked_key, role, permissions_json, created_by, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (key_id, workspace_id, tenant_id, key_hash, name.strip() or "Workspace API key", masked_key, role, json.dumps(permissions), created_by, now.isoformat(), now.isoformat(), expires_at.isoformat() if expires_at else None),
            )
        return ApiKeyRecord(key_id=key_id, workspace_id=workspace_id, name=name, masked_key=masked_key, role=role, permissions=permissions, created_by=created_by, created_at=now, expires_at=expires_at)

    def list_api_keys(self, workspace_id: str) -> list[ApiKeyRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM api_keys WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,)).fetchall()
        return [self._api_key_record(row) for row in rows]

    def revoke_api_key(self, workspace_id: str, key_id: str) -> bool:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute("UPDATE api_keys SET revoked_at = ?, updated_at = ? WHERE workspace_id = ? AND key_id = ? AND revoked_at IS NULL", (now, now, workspace_id, key_id))
            return cur.rowcount > 0

    def get_api_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)", (key_hash, now)).fetchone()
        return self._api_key_record(row) if row else None

    def create_workspace_invitation(
        self,
        *,
        workspace_id: str,
        tenant_id: str,
        email: str,
        role: str,
        invited_by: str,
        token_hash: str,
        expires_at: datetime,
    ) -> WorkspaceInvitationRecord:
        now = datetime.utcnow()
        invitation_id = str(uuid.uuid4())
        normalized_email = email.strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspace_invitations(invitation_id, workspace_id, tenant_id, email, role, invited_by, token_hash, status, expires_at, accepted_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, ?, ?)
                """,
                (invitation_id, workspace_id, tenant_id, normalized_email, role, invited_by, token_hash, expires_at.isoformat(), now.isoformat(), now.isoformat()),
            )
        return WorkspaceInvitationRecord(invitation_id=invitation_id, workspace_id=workspace_id, tenant_id=tenant_id, email=normalized_email, role=role, invited_by=invited_by, status="pending", expires_at=expires_at, created_at=now, updated_at=now)

    def get_pending_invitation_for_email(self, workspace_id: str, email: str, now: datetime | None = None) -> WorkspaceInvitationRecord | None:
        now = now or datetime.utcnow()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM workspace_invitations
                WHERE workspace_id = ? AND email = ? AND status = 'pending' AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id, email.strip().lower(), now.isoformat()),
            ).fetchone()
        return self._invitation_record(row) if row else None

    def get_pending_invitation_by_token_hash(self, token_hash: str, now: datetime | None = None) -> WorkspaceInvitationRecord | None:
        now = now or datetime.utcnow()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspace_invitations WHERE token_hash = ? AND status = 'pending' AND expires_at > ?",
                (token_hash, now.isoformat()),
            ).fetchone()
        return self._invitation_record(row) if row else None

    def list_workspace_invitations(self, workspace_id: str, include_inactive: bool = False) -> list[WorkspaceInvitationRecord]:
        with self._connect() as conn:
            if include_inactive:
                rows = conn.execute("SELECT * FROM workspace_invitations WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM workspace_invitations WHERE workspace_id = ? AND status = 'pending' ORDER BY created_at DESC", (workspace_id,)).fetchall()
        return [self._invitation_record(row) for row in rows]

    def revoke_workspace_invitation(self, workspace_id: str, invitation_id: str) -> bool:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE workspace_invitations SET status = 'revoked', updated_at = ? WHERE workspace_id = ? AND invitation_id = ? AND status = 'pending'",
                (now, workspace_id, invitation_id),
            )
            return cursor.rowcount > 0

    def accept_workspace_invitation(self, invitation_id: str, user_id: str) -> WorkspaceInvitationRecord | None:
        now = datetime.utcnow()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspace_invitations WHERE invitation_id = ? AND status = 'pending' AND expires_at > ?",
                (invitation_id, now.isoformat()),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE workspace_invitations SET status = 'accepted', accepted_at = ?, updated_at = ? WHERE invitation_id = ?",
                (now.isoformat(), now.isoformat(), invitation_id),
            )
            conn.execute(
                """
                INSERT INTO workspace_members(workspace_id, user_id, role, status, joined_at, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(workspace_id, user_id) DO UPDATE SET role = excluded.role, status = 'active', updated_at = excluded.updated_at
                """,
                (row["workspace_id"], user_id, row["role"], now.isoformat(), now.isoformat(), now.isoformat()),
            )
        return self.get_pending_invitation_by_token_hash(row["token_hash"], now=datetime.min) or self._invitation_record(dict(row) | {"status": "accepted", "accepted_at": now.isoformat(), "updated_at": now.isoformat()})

    def mark_api_key_used(self, key_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("UPDATE api_keys SET last_used_at = ?, updated_at = ? WHERE key_id = ?", (now, now, key_id))

    @staticmethod
    def _api_key_record(row) -> ApiKeyRecord:
        return ApiKeyRecord(
            key_id=row["key_id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            masked_key=row["masked_key"],
            role=row["role"],
            permissions=json.loads(row["permissions_json"] or "[]"),
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
            revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
        )

    @staticmethod
    def _invitation_record(row) -> WorkspaceInvitationRecord:
        status = row["status"]
        expires_at = datetime.fromisoformat(row["expires_at"])
        if status == "pending" and expires_at <= datetime.utcnow():
            status = "expired"
        return WorkspaceInvitationRecord(
            invitation_id=row["invitation_id"],
            workspace_id=row["workspace_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            role=row["role"],
            invited_by=row["invited_by"],
            status=status,
            expires_at=expires_at,
            accepted_at=datetime.fromisoformat(row["accepted_at"]) if row["accepted_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
        if row is None:
            return None
        return WorkspaceRecord(
            workspace_id=row["workspace_id"],
            name=row["name"],
            owner_id=row["owner_id"],
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default-tenant",
            private_mode=bool(row["private_mode"]),
            external_ai_allowed=bool(row["external_ai_allowed"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            metadata=json.loads(row["metadata_json"]),
        )

    def list_workspaces(self, owner_id: str | None = None) -> list[WorkspaceRecord]:
        with self._connect() as conn:
            if owner_id:
                rows = conn.execute("SELECT * FROM workspaces WHERE owner_id = ? ORDER BY created_at DESC", (owner_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at DESC").fetchall()
        return [
            WorkspaceRecord(
                workspace_id=row["workspace_id"],
                name=row["name"],
                owner_id=row["owner_id"],
                tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default-tenant",
                private_mode=bool(row["private_mode"]),
                external_ai_allowed=bool(row["external_ai_allowed"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def create_user(
        self,
        email: str,
        display_name: str | None = None,
        tenant_id: str = "default-tenant",
        preferences: dict[str, Any] | None = None,
    ) -> UserRecord:
        now = datetime.utcnow()
        record = UserRecord(
            user_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=email.strip().lower(),
            display_name=display_name,
            avatar_url=(preferences or {}).get("avatar_url"),
            auth_provider=(preferences or {}).get("auth_provider", "local"),
            provider_subject=(preferences or {}).get("provider_subject"),
            status=(preferences or {}).get("status", "active"),
            last_login_at=(preferences or {}).get("last_login_at"),
            created_at=now,
            updated_at=now,
            preferences=preferences or {},
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, tenant_id, email, display_name, avatar_url, auth_provider, provider_subject, status, last_login_at, created_at, updated_at, preferences_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.user_id,
                    record.tenant_id,
                    record.email,
                    record.display_name,
                    record.avatar_url,
                    record.auth_provider,
                    record.provider_subject,
                    record.status,
                    record.last_login_at.isoformat() if record.last_login_at else None,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    json.dumps(record.preferences),
                ),
            )
        return record

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            auth_provider=row["auth_provider"],
            provider_subject=row["provider_subject"],
            status=row["status"],
            last_login_at=datetime.fromisoformat(row["last_login_at"]) if row["last_login_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            preferences=json.loads(row["preferences_json"]),
        )

    def get_user(self, user_id: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            auth_provider=row["auth_provider"],
            provider_subject=row["provider_subject"],
            status=row["status"],
            last_login_at=datetime.fromisoformat(row["last_login_at"]) if row["last_login_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            preferences=json.loads(row["preferences_json"]),
        )

    def create_auth_session(self, token_hash: str, user_id: str, expires_at: datetime) -> None:
        now = datetime.utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions(session_token_hash, user_id, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (token_hash, user_id, now.isoformat(), expires_at.isoformat()),
            )

    def get_user_id_for_session(self, token_hash: str, now: datetime | None = None) -> str | None:
        now = now or datetime.utcnow()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT user_id FROM auth_sessions
                WHERE session_token_hash = ?
                  AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (token_hash, now.isoformat()),
            ).fetchone()
        return row["user_id"] if row else None

    def revoke_auth_session(self, token_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE session_token_hash = ?",
                (datetime.utcnow().isoformat(), token_hash),
            )

    def create_auth_action_token(
        self,
        token_hash: str,
        user_id: str,
        action: str,
        expires_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO auth_action_tokens(token_hash, user_id, action, created_at, expires_at, used_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (token_hash, user_id, action, now.isoformat(), expires_at.isoformat(), json.dumps(metadata or {})),
            )

    def consume_auth_action_token(self, token_hash: str, action: str, now: datetime | None = None) -> str | None:
        now = now or datetime.utcnow()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT user_id FROM auth_action_tokens
                WHERE token_hash = ?
                  AND action = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                """,
                (token_hash, action, now.isoformat()),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE auth_action_tokens SET used_at = ? WHERE token_hash = ?",
                (now.isoformat(), token_hash),
            )
            return row["user_id"]

    def update_user_preferences(self, user_id: str, preferences: dict[str, Any]) -> UserRecord | None:
        user = self.get_user(user_id)
        if user is None:
            return None
        merged = {**user.preferences, **preferences}
        now = datetime.utcnow()
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET preferences_json = ?, updated_at = ? WHERE user_id = ?",
                (json.dumps(merged), now.isoformat(), user_id),
            )
        user.preferences = merged
        user.status = str(merged.get("status", user.status))
        user.updated_at = now
        return user

    def update_user_auth_profile(self, user_id: str, *, auth_provider: str, provider_subject: str | None = None, display_name: str | None = None, avatar_url: str | None = None, email_verified: bool | None = None) -> UserRecord | None:
        user = self.get_user(user_id)
        if user is None:
            return None
        now = datetime.utcnow()
        merged = {
            **user.preferences,
            "auth_provider": auth_provider,
            "provider_subject": provider_subject or user.provider_subject,
            "avatar_url": avatar_url or user.avatar_url,
            "last_login_at": now.isoformat(),
        }
        if email_verified is not None:
            merged["email_verified"] = email_verified
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET auth_provider = ?, provider_subject = ?, display_name = COALESCE(?, display_name),
                    avatar_url = COALESCE(?, avatar_url), last_login_at = ?, updated_at = ?, preferences_json = ?
                WHERE user_id = ?
                """,
                (auth_provider, provider_subject or user.provider_subject, display_name, avatar_url, now.isoformat(), now.isoformat(), json.dumps(merged, default=str), user_id),
            )
        return self.get_user(user_id)

    def update_user_status(self, user_id: str, status: str) -> UserRecord | None:
        if status not in {"active", "disabled", "suspended"}:
            raise ValueError(f"Unsupported user status: {status}")
        user = self.get_user(user_id)
        if user is None:
            return None
        now = datetime.utcnow()
        merged = {**user.preferences, "status": status}
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET status = ?, preferences_json = ?, updated_at = ? WHERE user_id = ?",
                (status, json.dumps(merged), now.isoformat(), user_id),
            )
        return self.get_user(user_id)

    def upsert_ingestion_job(self, record: IngestionJobRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_jobs(job_id, workspace_id, filename, status, progress, document_id, message, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status,
                    progress=excluded.progress,
                    document_id=excluded.document_id,
                    message=excluded.message,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record.job_id,
                    record.workspace_id,
                    record.filename,
                    record.status,
                    record.progress,
                    record.document_id,
                    record.message,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat() if record.updated_at else None,
                    json.dumps(record.metadata),
                ),
            )

    def get_ingestion_job(self, job_id: str) -> IngestionJobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ingestion_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return IngestionJobRecord(
            job_id=row["job_id"],
            workspace_id=row["workspace_id"],
            filename=row["filename"],
            status=row["status"],
            progress=row["progress"],
            document_id=row["document_id"],
            message=row["message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            metadata=json.loads(row["metadata_json"]),
        )

    def create_chat_session(
        self,
        workspace_id: str,
        title: str | None,
        language: str,
        explanation_level: str,
        objective_profile: str = "general",
        analysis_mode: str = "quick",
        input_language: str | None = None,
        response_language: str | None = None,
    ) -> ChatSessionRecord:
        now = datetime.utcnow()
        input_language = input_language or language
        response_language = response_language or language
        record = ChatSessionRecord(
            session_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            title=title,
            language=response_language,
            input_language=input_language,
            response_language=response_language,
            explanation_level=explanation_level,
            objective_profile=objective_profile,
            analysis_mode=analysis_mode,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions(session_id, workspace_id, title, language, input_language, response_language, explanation_level, objective_profile, analysis_mode, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.workspace_id,
                    record.title,
                    record.language,
                    record.input_language,
                    record.response_language,
                    record.explanation_level,
                    record.objective_profile,
                    record.analysis_mode,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
        return record

    def get_chat_session(self, session_id: str) -> ChatSessionRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return ChatSessionRecord(
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            language=row["response_language"] if "response_language" in row.keys() else row["language"],
            input_language=row["input_language"] if "input_language" in row.keys() else row["language"],
            response_language=row["response_language"] if "response_language" in row.keys() else row["language"],
            explanation_level=row["explanation_level"],
            objective_profile=row["objective_profile"] if "objective_profile" in row.keys() else "general",
            analysis_mode=row["analysis_mode"] if "analysis_mode" in row.keys() else "quick",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    def list_chat_sessions(self, workspace_id: str, limit: int = 50) -> list[ChatSessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chat_sessions
                WHERE workspace_id = ?
                ORDER BY COALESCE(updated_at, created_at) DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        return [
            ChatSessionRecord(
                session_id=row["session_id"],
                workspace_id=row["workspace_id"],
                title=row["title"],
                language=row["response_language"] if "response_language" in row.keys() else row["language"],
                input_language=row["input_language"] if "input_language" in row.keys() else row["language"],
                response_language=row["response_language"] if "response_language" in row.keys() else row["language"],
                explanation_level=row["explanation_level"],
                objective_profile=row["objective_profile"] if "objective_profile" in row.keys() else "general",
                analysis_mode=row["analysis_mode"] if "analysis_mode" in row.keys() else "quick",
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            )
            for row in rows
        ]

    def add_chat_message(
        self,
        session_id: str,
        workspace_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessageRecord:
        record = ChatMessageRecord(
            message_id=str(uuid.uuid4()),
            session_id=session_id,
            workspace_id=workspace_id,
            role=role,
            content=content,
            language=(metadata or {}).get("language", "auto"),
            created_at=datetime.utcnow(),
            metadata=metadata or {},
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages(message_id, session_id, workspace_id, role, content, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.message_id,
                    record.session_id,
                    record.workspace_id,
                    record.role,
                    record.content,
                    record.created_at.isoformat(),
                    json.dumps(record.metadata),
                ),
            )
            title = content.strip().replace("\n", " ")[:80] if role == "user" else None
            if title:
                conn.execute(
                    """
                    UPDATE chat_sessions
                    SET updated_at = ?, title = COALESCE(title, ?)
                    WHERE session_id = ?
                    """,
                    (record.created_at.isoformat(), title, session_id),
                )
            else:
                conn.execute(
                    "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                    (record.created_at.isoformat(), session_id),
                )
        return record

    def list_chat_messages(self, session_id: str, limit: int = 50) -> list[ChatMessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        records = [
            ChatMessageRecord(
                message_id=row["message_id"],
                session_id=row["session_id"],
                workspace_id=row["workspace_id"],
                role=row["role"],
                content=row["content"],
                language=json.loads(row["metadata_json"]).get("language", "auto"),
                created_at=datetime.fromisoformat(row["created_at"]),
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]
        return list(reversed(records))

    def upsert_memory(self, record: MemoryRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_records(memory_id, session_id, workspace_id, user_id, objective_profile, memory_type, content, entities_json, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    content=excluded.content,
                    entities_json=excluded.entities_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.memory_id,
                    record.session_id,
                    record.workspace_id,
                    record.user_id,
                    record.objective_profile,
                    record.memory_type,
                    record.content,
                    json.dumps(record.entities),
                    json.dumps(record.metadata),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat() if record.updated_at else None,
                ),
            )

    def list_memory(self, session_id: str, limit: int = 20) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_records WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        records = [
            MemoryRecord(
                memory_id=row["memory_id"],
                session_id=row["session_id"],
                workspace_id=row["workspace_id"],
                user_id=row["user_id"],
                objective_profile=row["objective_profile"],
                memory_type=row["memory_type"],
                content=row["content"],
                entities=json.loads(row["entities_json"]),
                metadata=json.loads(row["metadata_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            )
            for row in rows
        ]
        return list(reversed(records))

    def list_workspace_memory(
        self,
        workspace_id: str,
        objective_profile: str | None = None,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        clauses = ["workspace_id = ?"]
        params: list[Any] = [workspace_id]
        if objective_profile:
            clauses.append("objective_profile IN (?, 'general')")
            params.append(objective_profile)
        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memory_records WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
        records = [
            MemoryRecord(
                memory_id=row["memory_id"],
                session_id=row["session_id"],
                workspace_id=row["workspace_id"],
                user_id=row["user_id"],
                objective_profile=row["objective_profile"],
                memory_type=row["memory_type"],
                content=row["content"],
                entities=json.loads(row["entities_json"]),
                metadata=json.loads(row["metadata_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            )
            for row in rows
        ]
        return records

    def upsert_extracted_artifact(self, artifact: ExtractedArtifact) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO extracted_artifacts(artifact_id, document_id, workspace_id, artifact_type, page_number, title, text, data_json, bbox_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.document_id,
                    artifact.workspace_id,
                    artifact.artifact_type,
                    artifact.page_number,
                    artifact.title,
                    artifact.text,
                    json.dumps(artifact.data),
                    json.dumps(artifact.bbox) if artifact.bbox else None,
                    artifact.created_at.isoformat(),
                ),
            )

    def upsert_evidence_anchor(self, anchor: EvidenceAnchorRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO evidence_anchors(
                    anchor_id, document_id, workspace_id, chunk_id, artifact_id, anchor_type,
                    page_number, bbox_json, preview_path, crop_path, citation_text, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anchor.anchor_id,
                    anchor.document_id,
                    anchor.workspace_id,
                    anchor.chunk_id,
                    anchor.artifact_id,
                    anchor.anchor_type,
                    anchor.page_number,
                    json.dumps(anchor.bbox) if anchor.bbox else None,
                    anchor.preview_path,
                    anchor.crop_path,
                    anchor.citation_text,
                    json.dumps(anchor.metadata),
                    anchor.created_at.isoformat(),
                ),
            )

    def get_evidence_anchor(self, anchor_id: str) -> EvidenceAnchorRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evidence_anchors WHERE anchor_id = ?", (anchor_id,)).fetchone()
        return self._row_to_evidence_anchor(row) if row else None

    def list_evidence_anchors(
        self,
        document_id: str | None = None,
        workspace_id: str | None = None,
        chunk_id: str | None = None,
        limit: int = 100,
    ) -> list[EvidenceAnchorRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if document_id:
            clauses.append("document_id = ?")
            params.append(document_id)
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if chunk_id:
            clauses.append("chunk_id = ?")
            params.append(chunk_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM evidence_anchors {where} ORDER BY page_number, created_at LIMIT ?", params).fetchall()
        return [self._row_to_evidence_anchor(row) for row in rows]

    def list_extracted_artifacts(self, document_id: str, artifact_type: str | None = None) -> list[ExtractedArtifact]:
        with self._connect() as conn:
            if artifact_type:
                rows = conn.execute(
                    "SELECT * FROM extracted_artifacts WHERE document_id = ? AND artifact_type = ? ORDER BY page_number",
                    (document_id, artifact_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM extracted_artifacts WHERE document_id = ? ORDER BY page_number",
                    (document_id,),
                ).fetchall()
        return [
            ExtractedArtifact(
                artifact_id=row["artifact_id"],
                document_id=row["document_id"],
                workspace_id=row["workspace_id"],
                artifact_type=row["artifact_type"],
                page_number=row["page_number"],
                title=row["title"],
                text=row["text"],
                data=json.loads(row["data_json"]),
                bbox=json.loads(row["bbox_json"]) if row["bbox_json"] else None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def log_agent_run(self, run: AgentRun) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_runs(run_id, session_id, workspace_id, objective_profile, analysis_mode, steps_json, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.session_id,
                    run.workspace_id,
                    run.objective_profile,
                    run.analysis_mode,
                    json.dumps([step.model_dump(mode="json") for step in run.steps]),
                    run.created_at.isoformat(),
                    json.dumps(run.metadata),
                ),
            )

    def add_audit_log(
        self,
        event_type: str,
        *,
        user: UserRecord | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        status: str = "success",
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLogRecord:
        now = datetime.utcnow()
        record = AuditLogRecord(
            audit_id=str(uuid.uuid4()),
            tenant_id=tenant_id or (user.tenant_id if user else "default-tenant"),
            workspace_id=workspace_id,
            user_id=user.user_id if user else "local-user",
            event_type=event_type,
            actor_email=user.email if user else None,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,  # type: ignore[arg-type]
            message=message,
            metadata=metadata or {},
            created_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs(
                    audit_id, tenant_id, workspace_id, user_id, event_type, actor_email,
                    resource_type, resource_id, status, message, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.audit_id,
                    record.tenant_id,
                    record.workspace_id,
                    record.user_id,
                    record.event_type,
                    record.actor_email,
                    record.resource_type,
                    record.resource_id,
                    record.status,
                    record.message,
                    json.dumps(record.metadata),
                    record.created_at.isoformat(),
                ),
            )
        return record

    def list_audit_logs(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            AuditLogRecord(
                audit_id=row["audit_id"],
                tenant_id=row["tenant_id"],
                workspace_id=row["workspace_id"],
                user_id=row["user_id"],
                event_type=row["event_type"],
                actor_email=row["actor_email"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                status=row["status"],
                message=row["message"],
                metadata=json.loads(row["metadata_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def upsert_document(self, record: DocumentRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents(document_id, workspace_id, filename, source_path, fingerprint, status, page_count, ingested_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    workspace_id=excluded.workspace_id,
                    filename=excluded.filename,
                    source_path=excluded.source_path,
                    fingerprint=excluded.fingerprint,
                    status=excluded.status,
                    page_count=excluded.page_count,
                    ingested_at=excluded.ingested_at,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record.document_id,
                    record.workspace_id,
                    record.filename,
                    record.source_path,
                    record.fingerprint,
                    record.status,
                    record.page_count,
                    record.ingested_at.isoformat(),
                    record.updated_at.isoformat() if record.updated_at else None,
                    json.dumps(record.metadata),
                ),
            )

    def insert_chunks(self, chunks: list[ChunkRecord]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO chunks(chunk_id, document_id, workspace_id, filename, page_number, text, section, token_count, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.workspace_id,
                        chunk.filename,
                        chunk.page_number,
                        chunk.text,
                        chunk.section,
                        chunk.token_count,
                        json.dumps(
                            {
                                **chunk.metadata,
                                "chunk_position": chunk.chunk_position,
                                "prev_chunk_id": chunk.prev_chunk_id,
                                "next_chunk_id": chunk.next_chunk_id,
                            }
                        ),
                    )
                    for chunk in chunks
                ],
            )

    def list_documents(self, workspace_id: str | None = None) -> list[DocumentRecord]:
        with self._connect() as conn:
            if workspace_id:
                rows = conn.execute("SELECT * FROM documents WHERE workspace_id = ? ORDER BY ingested_at DESC", (workspace_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM documents ORDER BY ingested_at DESC").fetchall()
        return [
            DocumentRecord(
                document_id=row["document_id"],
                workspace_id=row["workspace_id"] or "default",
                filename=row["filename"],
                source_path=row["source_path"],
                fingerprint=row["fingerprint"] or "",
                status=row["status"] or "processing",
                page_count=row["page_count"],
                ingested_at=datetime.fromisoformat(row["ingested_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def repair_document_records(self) -> dict[str, int]:
        repaired_status = 0
        repaired_fingerprint = 0
        repaired_updated_at = 0
        for record in self.list_documents():
            changed = False
            if not record.fingerprint:
                source_path = Path(record.source_path)
                if source_path.exists() and source_path.is_file():
                    record.fingerprint = self._fingerprint_file(source_path)
                    repaired_fingerprint += 1
                    changed = True
            if record.status == "processing" and self.has_chunks_for_document(record.document_id):
                record.status = "indexed"
                repaired_status += 1
                changed = True
            if record.updated_at is None:
                record.updated_at = record.ingested_at
                repaired_updated_at += 1
                changed = True
            if changed:
                self.upsert_document(record)
        return {
            "status_repaired": repaired_status,
            "fingerprint_repaired": repaired_fingerprint,
            "updated_at_repaired": repaired_updated_at,
        }

    def get_document_by_fingerprint(self, fingerprint: str, workspace_id: str = "default") -> DocumentRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE fingerprint = ? AND workspace_id = ? ORDER BY ingested_at DESC LIMIT 1",
                (fingerprint, workspace_id),
            ).fetchone()
        if row is None:
            return None
        return DocumentRecord(
            document_id=row["document_id"],
            workspace_id=row["workspace_id"] or "default",
            filename=row["filename"],
            source_path=row["source_path"],
            fingerprint=row["fingerprint"] or "",
            status=row["status"] or "processing",
            page_count=row["page_count"],
            ingested_at=datetime.fromisoformat(row["ingested_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            metadata=json.loads(row["metadata_json"]),
        )

    def get_document(self, document_id: str, workspace_id: str | None = None) -> DocumentRecord | None:
        with self._connect() as conn:
            if workspace_id:
                row = conn.execute(
                    "SELECT * FROM documents WHERE document_id = ? AND workspace_id = ?",
                    (document_id, workspace_id),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM documents WHERE document_id = ?", (document_id,)).fetchone()
        if row is None:
            return None
        return DocumentRecord(
            document_id=row["document_id"],
            workspace_id=row["workspace_id"] or "default",
            filename=row["filename"],
            source_path=row["source_path"],
            fingerprint=row["fingerprint"] or "",
            status=row["status"] or "processing",
            page_count=row["page_count"],
            ingested_at=datetime.fromisoformat(row["ingested_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            metadata=json.loads(row["metadata_json"]),
        )

    def get_chunk(self, chunk_id: str) -> ChunkRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_chunk(row)

    def get_chunks(self, chunk_ids: list[str], workspace_id: str | None = None, document_ids: list[str] | None = None) -> list[ChunkRecord]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as conn:
            clauses = [f"chunk_id IN ({placeholders})"]
            params: list[Any] = list(chunk_ids)
            if workspace_id:
                clauses.append("workspace_id = ?")
                params.append(workspace_id)
            if document_ids:
                doc_placeholders = ",".join("?" for _ in document_ids)
                clauses.append(f"document_id IN ({doc_placeholders})")
                params.extend(document_ids)
            rows = conn.execute(f"SELECT * FROM chunks WHERE {' AND '.join(clauses)}", params).fetchall()
        by_id = {row["chunk_id"]: self._row_to_chunk(row) for row in rows}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    def list_chunks(self, document_id: str | None = None, workspace_id: str | None = None) -> list[ChunkRecord]:
        with self._connect() as conn:
            if document_id:
                rows = conn.execute(
                    "SELECT * FROM chunks WHERE document_id = ? ORDER BY page_number, chunk_id",
                    (document_id,),
                ).fetchall()
            elif workspace_id:
                rows = conn.execute(
                    "SELECT * FROM chunks WHERE workspace_id = ? ORDER BY page_number, chunk_id",
                    (workspace_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM chunks ORDER BY page_number, chunk_id").fetchall()
        return [
            self._row_to_chunk(row)
            for row in rows
        ]

    def chunk_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()
        return int(row["count"])

    def has_chunks_for_document(self, document_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM chunks WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return bool(int(row["count"]))

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as conn:
            conn.execute(f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})", chunk_ids)

    def delete_document(self, document_id: str, workspace_id: str) -> list[str]:
        document = self.get_document(document_id, workspace_id=workspace_id)
        if document is None:
            return []
        chunk_ids = [chunk.chunk_id for chunk in self.list_chunks(document_id=document_id)]
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE document_id = ? AND workspace_id = ?", (document_id, workspace_id))
            conn.execute("DELETE FROM documents WHERE document_id = ? AND workspace_id = ?", (document_id, workspace_id))
        return chunk_ids

    def log_query(self, query_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO query_logs(query_id, payload_json, created_at) VALUES (?, ?, ?)",
                (query_id, json.dumps(payload), datetime.utcnow().isoformat()),
            )

    def recent_query_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM query_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def upsert_purge_job(self, record: PurgeJobRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO purge_jobs(
                    purge_job_id, workspace_id, document_id, status, reason, requested_by,
                    receipt_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.purge_job_id,
                    record.workspace_id,
                    record.document_id,
                    record.status,
                    record.reason,
                    record.requested_by,
                    json.dumps(record.receipt),
                    record.error,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat() if record.updated_at else None,
                ),
            )

    def create_deletion_request(self, record: DeletionRequestRecord) -> DeletionRequestRecord:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO deletion_requests(request_id, tenant_id, workspace_id, document_id, requested_by, reason, status, approved_by, created_at, updated_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.request_id, record.tenant_id, record.workspace_id, record.document_id, record.requested_by, record.reason, record.status, record.approved_by, record.created_at.isoformat(), record.updated_at.isoformat() if record.updated_at else None, json.dumps(record.metadata)),
            )
        return record

    def list_deletion_requests(self, workspace_id: str, limit: int = 100) -> list[DeletionRequestRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM deletion_requests WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?", (workspace_id, limit)).fetchall()
        return [self._row_to_deletion_request(row) for row in rows]

    def get_deletion_request(self, request_id: str, workspace_id: str | None = None) -> DeletionRequestRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM deletion_requests WHERE request_id = ?" + (" AND workspace_id = ?" if workspace_id else ""), (request_id, workspace_id) if workspace_id else (request_id,)).fetchone()
        return self._row_to_deletion_request(row) if row else None

    def update_deletion_request(self, request_id: str, *, status: str, approved_by: str | None = None) -> DeletionRequestRecord | None:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("UPDATE deletion_requests SET status = ?, approved_by = COALESCE(?, approved_by), updated_at = ? WHERE request_id = ?", (status, approved_by, now, request_id))
        return self.get_deletion_request(request_id)

    @staticmethod
    def _row_to_deletion_request(row) -> DeletionRequestRecord:
        return DeletionRequestRecord(
            request_id=row["request_id"], tenant_id=row["tenant_id"], workspace_id=row["workspace_id"], document_id=row["document_id"],
            requested_by=row["requested_by"], reason=row["reason"], status=row["status"], approved_by=row["approved_by"],
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            metadata=json.loads(row["metadata_json"]),
        )

    def list_purge_jobs(self, workspace_id: str, limit: int = 50) -> list[PurgeJobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM purge_jobs WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            ).fetchall()
        return [self._row_to_purge_job(row) for row in rows]

    def _row_to_purge_job(self, row: sqlite3.Row) -> PurgeJobRecord:
        return PurgeJobRecord(
            purge_job_id=row["purge_job_id"],
            workspace_id=row["workspace_id"],
            document_id=row["document_id"],
            status=row["status"],
            reason=row["reason"],
            requested_by=row["requested_by"],
            receipt=json.loads(row["receipt_json"] or "{}"),
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    def log_evaluation_run(self, run_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO evaluation_runs(run_id, payload_json, created_at) VALUES (?, ?, ?)",
                (run_id, json.dumps(payload), datetime.utcnow().isoformat()),
            )

    def list_evaluation_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM evaluation_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def _row_to_chunk(self, row: sqlite3.Row) -> ChunkRecord:
        metadata = json.loads(row["metadata_json"])
        return ChunkRecord(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            workspace_id=row["workspace_id"] or "default",
            filename=row["filename"],
            page_number=row["page_number"],
            text=row["text"],
            section=row["section"],
            token_count=row["token_count"],
            chunk_position=metadata.get("chunk_position"),
            prev_chunk_id=metadata.get("prev_chunk_id"),
            next_chunk_id=metadata.get("next_chunk_id"),
            metadata=metadata,
            content_type=metadata.get("content_type", "text"),
            bbox=metadata.get("bbox"),
            section_path=metadata.get("section_path", []),
            visual_caption=metadata.get("visual_caption"),
            table_json=metadata.get("table_json"),
            chart_series=metadata.get("chart_series"),
            risk_tags=metadata.get("risk_tags", []),
        )

    @staticmethod
    def _row_to_evidence_anchor(row: sqlite3.Row) -> EvidenceAnchorRecord:
        return EvidenceAnchorRecord(
            anchor_id=row["anchor_id"],
            document_id=row["document_id"],
            workspace_id=row["workspace_id"],
            chunk_id=row["chunk_id"],
            artifact_id=row["artifact_id"],
            anchor_type=row["anchor_type"],
            page_number=row["page_number"],
            bbox=json.loads(row["bbox_json"]) if row["bbox_json"] else None,
            preview_path=row["preview_path"],
            crop_path=row["crop_path"],
            citation_text=row["citation_text"],
            metadata=json.loads(row["metadata_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _fingerprint_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

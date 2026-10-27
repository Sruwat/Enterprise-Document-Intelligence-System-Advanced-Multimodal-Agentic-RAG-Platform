from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, inspect, select, text

from app.core.schemas import (
    AgentRun as AgentRunRecord,
    ApiKeyRecord,
    AuditLogRecord,
    ChatMessageRecord,
    ChatSessionRecord,
    ChunkRecord,
    DocumentRecord,
    EvidenceAnchorRecord,
    ExtractedArtifact as ExtractedArtifactRecord,
    IngestionJobRecord,
    MemoryRecord as MemoryRecordSchema,
    PurgeJobRecord,
    DeletionRequestRecord,
    UserRecord,
    WorkspaceInvitationRecord,
    WorkspaceRecord,
)
from app.db import models
from app.db.base import Base, build_engine, session_scope


class PostgresMetadataRepository:
    """SQLAlchemy metadata repository used when DATABASE_BACKEND=postgres.

    The method names intentionally mirror the SQLite MetadataStore so the rest
    of the app can move behind this repository boundary incrementally.
    """

    def __init__(self, database_url: str, *, create_schema: bool = True) -> None:
        self.database_url = database_url
        self.db_path = Path(database_url)
        self.engine = build_engine(database_url)
        if create_schema:
            self.create_schema()
            self._ensure_default_workspace()

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def table_names(self) -> list[str]:
        return sorted(inspect(self.engine).get_table_names())

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with session_scope(self.database_url) as session:
            for name, table in Base.metadata.tables.items():
                counts[name] = int(session.execute(select(func.count()).select_from(table)).scalar_one())
        return counts

    def schema_status(self) -> dict:
        return {"tables": self.table_names(), "table_count": len(self.table_names())}

    def runtime_status(self) -> dict[str, Any]:
        required_tables = {
            "users",
            "workspaces",
            "documents",
            "chunks",
            "chat_sessions",
            "chat_messages",
            "memory_records",
            "graph_entities",
            "graph_relationships",
            "query_logs",
            "api_keys",
            "ingestion_jobs",
            "workspace_invitations",
        }
        try:
            with session_scope(self.database_url) as session:
                select_one = session.execute(text("SELECT 1")).scalar_one()
                if self.engine.dialect.name == "postgresql":
                    database_name = session.execute(text("SELECT current_database()")).scalar_one_or_none()
                    database_user = session.execute(text("SELECT current_user")).scalar_one_or_none()
                else:
                    database_name = self.engine.dialect.name
                    database_user = None
                tables = set(self.table_names())
                counts = self.table_counts()
                migration_revision = None
                if "alembic_version" in tables:
                    migration_revision = session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
            missing_tables = sorted(required_tables - tables)
            return {
                "status": "ok" if select_one == 1 and not missing_tables else "error",
                "select_1": select_one == 1,
                "database": database_name,
                "user": database_user,
                "migration_revision": migration_revision,
                "table_count": len(tables),
                "required_tables": sorted(required_tables),
                "missing_tables": missing_tables,
                "table_counts": {name: counts.get(name, 0) for name in sorted(required_tables) if name in counts},
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc), "database_url": str(self.database_url)}

    def _ensure_default_workspace(self) -> None:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            if session.get(models.Tenant, "default-tenant") is None:
                session.add(models.Tenant(id="default-tenant", name="Default Tenant", plan="free", created_at=now, updated_at=now, metadata_json={}))
            if session.get(models.User, "local-user") is None:
                session.add(
                    models.User(
                        id="local-user",
                        tenant_id="default-tenant",
                        email="local@aiwana.dev",
                        display_name="Local User",
                        created_at=now,
                        updated_at=now,
                        metadata_json={},
                    )
                )
            if session.get(models.UserPreference, "local-user") is None:
                session.add(models.UserPreference(user_id="local-user", metadata_json={}))
            if session.get(models.Workspace, "default") is None:
                session.add(
                    models.Workspace(
                        id="default",
                        tenant_id="default-tenant",
                        owner_id="local-user",
                        name="Default Knowledge Space",
                        private_mode=False,
                        external_ai_allowed=True,
                        created_at=now,
                        updated_at=now,
                        metadata_json={},
                    )
                )
            self._ensure_workspace_member(session, "default", "local-user", "default-tenant", "owner")

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
        with session_scope(self.database_url) as session:
            self._ensure_tenant(session, record.tenant_id)
            self._ensure_user(session, record.owner_id, record.tenant_id)
            session.merge(
                models.Workspace(
                    id=record.workspace_id,
                    tenant_id=record.tenant_id,
                    owner_id=record.owner_id,
                    name=record.name,
                    private_mode=record.private_mode,
                    external_ai_allowed=record.external_ai_allowed,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    metadata_json=record.metadata,
                )
            )
            self._ensure_workspace_member(session, record.workspace_id, record.owner_id, record.tenant_id, "owner")
        return record

    def set_workspace_member(self, workspace_id: str, user_id: str, role: str) -> None:
        normalized = role.strip().lower()
        if normalized not in {"owner", "admin", "analyst", "viewer"}:
            raise ValueError(f"Unsupported workspace role: {role}")
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            raise ValueError(f"Unknown workspace: {workspace_id}")
        with session_scope(self.database_url) as session:
            self._ensure_user(session, user_id, workspace.tenant_id)
            self._ensure_workspace_member(session, workspace_id, user_id, workspace.tenant_id, normalized)

    def get_workspace_member_role(self, workspace_id: str, user_id: str) -> str | None:
        with session_scope(self.database_url) as session:
            stmt = (
                select(models.Role.name)
                .join(models.WorkspaceMember, models.WorkspaceMember.role_id == models.Role.id)
                .where(models.WorkspaceMember.workspace_id == workspace_id, models.WorkspaceMember.user_id == user_id)
            )
            role = session.execute(stmt).scalar_one_or_none()
            return str(role).lower() if role else None

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
        with session_scope(self.database_url) as session:
            session.add(
                models.ApiKey(
                    id=key_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    key_hash=key_hash,
                    name=name.strip() or "Workspace API key",
                    masked_key=masked_key,
                    role=role,
                    permissions_json=permissions,
                    created_by=created_by,
                    expires_at=expires_at,
                    created_at=now,
                    updated_at=now,
                )
            )
        return ApiKeyRecord(key_id=key_id, workspace_id=workspace_id, name=name, masked_key=masked_key, role=role, permissions=permissions, created_by=created_by, created_at=now, expires_at=expires_at)

    def list_api_keys(self, workspace_id: str) -> list[ApiKeyRecord]:
        with session_scope(self.database_url) as session:
            rows = session.execute(select(models.ApiKey).where(models.ApiKey.workspace_id == workspace_id).order_by(models.ApiKey.created_at.desc())).scalars().all()
            return [self._api_key_record(row) for row in rows]

    def revoke_api_key(self, workspace_id: str, key_id: str) -> bool:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.execute(select(models.ApiKey).where(models.ApiKey.workspace_id == workspace_id, models.ApiKey.id == key_id, models.ApiKey.revoked_at.is_(None))).scalar_one_or_none()
            if row is None:
                return False
            row.revoked_at = now
            row.updated_at = now
            session.merge(row)
            return True

    def get_api_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        with session_scope(self.database_url) as session:
            now = datetime.utcnow()
            row = session.execute(
                select(models.ApiKey).where(
                    models.ApiKey.key_hash == key_hash,
                    models.ApiKey.revoked_at.is_(None),
                    ((models.ApiKey.expires_at.is_(None)) | (models.ApiKey.expires_at > now)),
                )
            ).scalar_one_or_none()
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
        with session_scope(self.database_url) as session:
            session.add(
                models.WorkspaceInvitation(
                    id=invitation_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    email=normalized_email,
                    role=role,
                    invited_by=invited_by,
                    token_hash=token_hash,
                    status="pending",
                    expires_at=expires_at,
                    created_at=now,
                    updated_at=now,
                )
            )
        return WorkspaceInvitationRecord(
            invitation_id=invitation_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            email=normalized_email,
            role=role,  # type: ignore[arg-type]
            invited_by=invited_by,
            status="pending",
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

    def get_pending_invitation_for_email(self, workspace_id: str, email: str, now: datetime | None = None) -> WorkspaceInvitationRecord | None:
        now = now or datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.execute(
                select(models.WorkspaceInvitation)
                .where(
                    models.WorkspaceInvitation.workspace_id == workspace_id,
                    models.WorkspaceInvitation.email == email.strip().lower(),
                    models.WorkspaceInvitation.status == "pending",
                    models.WorkspaceInvitation.expires_at > now,
                )
                .order_by(models.WorkspaceInvitation.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            return self._invitation_record(row) if row else None

    def get_pending_invitation_by_token_hash(self, token_hash: str, now: datetime | None = None) -> WorkspaceInvitationRecord | None:
        now = now or datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.execute(
                select(models.WorkspaceInvitation).where(
                    models.WorkspaceInvitation.token_hash == token_hash,
                    models.WorkspaceInvitation.status == "pending",
                    models.WorkspaceInvitation.expires_at > now,
                )
            ).scalar_one_or_none()
            return self._invitation_record(row) if row else None

    def list_workspace_invitations(self, workspace_id: str, include_inactive: bool = False) -> list[WorkspaceInvitationRecord]:
        with session_scope(self.database_url) as session:
            stmt = select(models.WorkspaceInvitation).where(models.WorkspaceInvitation.workspace_id == workspace_id)
            if not include_inactive:
                stmt = stmt.where(models.WorkspaceInvitation.status == "pending")
            rows = session.execute(stmt.order_by(models.WorkspaceInvitation.created_at.desc())).scalars().all()
            return [self._invitation_record(row) for row in rows]

    def revoke_workspace_invitation(self, workspace_id: str, invitation_id: str) -> bool:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.execute(
                select(models.WorkspaceInvitation).where(
                    models.WorkspaceInvitation.workspace_id == workspace_id,
                    models.WorkspaceInvitation.id == invitation_id,
                    models.WorkspaceInvitation.status == "pending",
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            row.status = "revoked"
            row.updated_at = now
            session.merge(row)
            return True

    def accept_workspace_invitation(self, invitation_id: str, user_id: str) -> WorkspaceInvitationRecord | None:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.get(models.WorkspaceInvitation, invitation_id)
            if row is None or row.status != "pending" or row.expires_at <= now:
                return None
            row.status = "accepted"
            row.accepted_at = now
            row.updated_at = now
            self._ensure_workspace_member(session, row.workspace_id, user_id, row.tenant_id, row.role)
            session.merge(row)
            return self._invitation_record(row)

    def mark_api_key_used(self, key_id: str) -> None:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.get(models.ApiKey, key_id)
            if row:
                row.last_used_at = now
                row.updated_at = now
                session.merge(row)

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        with session_scope(self.database_url) as session:
            row = session.get(models.Workspace, workspace_id)
            return self._workspace_record(row) if row else None

    def list_workspaces(self, owner_id: str | None = None) -> list[WorkspaceRecord]:
        with session_scope(self.database_url) as session:
            stmt = select(models.Workspace)
            if owner_id:
                stmt = stmt.where(models.Workspace.owner_id == owner_id)
            rows = session.execute(stmt.order_by(models.Workspace.created_at.desc())).scalars().all()
            return [self._workspace_record(row) for row in rows]

    def create_user(
        self,
        email: str,
        display_name: str | None = None,
        tenant_id: str = "default-tenant",
        preferences: dict[str, Any] | None = None,
    ) -> UserRecord:
        now = datetime.utcnow()
        preferences = preferences or {}
        record = UserRecord(
            user_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=email.strip().lower(),
            display_name=display_name,
            avatar_url=preferences.get("avatar_url"),
            auth_provider=preferences.get("auth_provider", "local"),
            provider_subject=preferences.get("provider_subject"),
            status=preferences.get("status", "active"),
            last_login_at=preferences.get("last_login_at"),
            created_at=now,
            updated_at=now,
            preferences=dict(preferences),
        )
        with session_scope(self.database_url) as session:
            self._ensure_tenant(session, record.tenant_id)
            session.merge(
                models.User(
                    id=record.user_id,
                    tenant_id=record.tenant_id,
                    email=record.email,
                    display_name=record.display_name,
                    avatar_url=record.avatar_url,
                    auth_provider=record.auth_provider,
                    provider_subject=record.provider_subject,
                    password_hash=preferences.get("password_hash"),
                    password_salt=preferences.get("password_salt"),
                    email_verified=bool(preferences.get("email_verified", False)),
                    status=record.status,
                    last_login_at=record.last_login_at,
                    created_at=now,
                    updated_at=now,
                    metadata_json={k: v for k, v in preferences.items() if k not in {"password_hash", "password_salt", "email_verified"}},
                )
            )
            session.merge(models.UserPreference(user_id=record.user_id, metadata_json=dict(preferences)))
        return record

    def update_user_auth_profile(self, user_id: str, *, auth_provider: str, provider_subject: str | None = None, display_name: str | None = None, avatar_url: str | None = None, email_verified: bool | None = None) -> UserRecord | None:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            user = session.get(models.User, user_id)
            if user is None:
                return None
            user.auth_provider = auth_provider
            user.provider_subject = provider_subject or user.provider_subject
            user.display_name = display_name or user.display_name
            user.avatar_url = avatar_url or user.avatar_url
            user.last_login_at = now
            if email_verified is not None:
                user.email_verified = email_verified
            user.updated_at = now
            preferences = self._preferences_for_user(session, user)
            preferences.update(
                {
                    "auth_provider": user.auth_provider,
                    "provider_subject": user.provider_subject,
                    "avatar_url": user.avatar_url,
                    "last_login_at": now,
                    "email_verified": user.email_verified,
                }
            )
            pref = session.get(models.UserPreference, user_id) or models.UserPreference(user_id=user_id)
            pref.metadata_json = preferences
            session.merge(pref)
            return self._user_record(session, user, preferences=preferences)

    def update_user_status(self, user_id: str, status: str) -> UserRecord | None:
        if status not in {"active", "disabled", "suspended"}:
            raise ValueError(f"Unsupported user status: {status}")
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            user = session.get(models.User, user_id)
            if user is None:
                return None
            user.status = status
            user.updated_at = now
            preferences = self._preferences_for_user(session, user)
            preferences["status"] = status
            pref = session.get(models.UserPreference, user_id) or models.UserPreference(user_id=user_id)
            pref.metadata_json = preferences
            session.merge(pref)
            return self._user_record(session, user, preferences=preferences)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with session_scope(self.database_url) as session:
            row = session.execute(select(models.User).where(models.User.email == email.strip().lower())).scalar_one_or_none()
            return self._user_record(session, row) if row else None

    def get_user(self, user_id: str) -> UserRecord | None:
        with session_scope(self.database_url) as session:
            row = session.get(models.User, user_id)
            return self._user_record(session, row) if row else None

    def create_auth_session(self, token_hash: str, user_id: str, expires_at: datetime) -> None:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.execute(select(models.AuthSession).where(models.AuthSession.session_token_hash == token_hash)).scalar_one_or_none()
            if row is None:
                row = models.AuthSession(id=str(uuid.uuid4()), session_token_hash=token_hash, created_at=now)
            row.user_id = user_id
            row.expires_at = expires_at
            row.revoked_at = None
            row.updated_at = now
            session.merge(row)

    def get_user_id_for_session(self, token_hash: str, now: datetime | None = None) -> str | None:
        now = now or datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.execute(
                select(models.AuthSession).where(
                    models.AuthSession.session_token_hash == token_hash,
                    models.AuthSession.expires_at > now,
                    models.AuthSession.revoked_at.is_(None),
                )
            ).scalar_one_or_none()
            return row.user_id if row else None

    def revoke_auth_session(self, token_hash: str) -> None:
        with session_scope(self.database_url) as session:
            row = session.execute(select(models.AuthSession).where(models.AuthSession.session_token_hash == token_hash)).scalar_one_or_none()
            if row:
                row.revoked_at = datetime.utcnow()
                row.updated_at = row.revoked_at

    def create_auth_action_token(self, token_hash: str, user_id: str, action: str, expires_at: datetime, metadata: dict[str, Any] | None = None) -> None:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            session.merge(
                models.AuthActionToken(
                    token_hash=token_hash,
                    user_id=user_id,
                    action=action,
                    expires_at=expires_at,
                    used_at=None,
                    metadata_json=metadata or {},
                    created_at=now,
                    updated_at=now,
                )
            )

    def consume_auth_action_token(self, token_hash: str, action: str, now: datetime | None = None) -> str | None:
        now = now or datetime.utcnow()
        with session_scope(self.database_url) as session:
            row = session.execute(
                select(models.AuthActionToken).where(
                    models.AuthActionToken.token_hash == token_hash,
                    models.AuthActionToken.action == action,
                    models.AuthActionToken.expires_at > now,
                    models.AuthActionToken.used_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.used_at = now
            row.updated_at = now
            return row.user_id

    def update_user_preferences(self, user_id: str, preferences: dict[str, Any]) -> UserRecord | None:
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            user = session.get(models.User, user_id)
            if user is None:
                return None
            current = self._preferences_for_user(session, user)
            current.update(preferences)
            if "password_hash" in preferences:
                user.password_hash = preferences["password_hash"]
            if "password_salt" in preferences:
                user.password_salt = preferences["password_salt"]
            if "email_verified" in preferences:
                user.email_verified = bool(preferences["email_verified"])
            user.updated_at = now
            pref = session.get(models.UserPreference, user_id) or models.UserPreference(user_id=user_id)
            pref.metadata_json = current
            session.merge(pref)
            return self._user_record(session, user, preferences=current)

    def upsert_ingestion_job(self, record: IngestionJobRecord) -> None:
        now = record.updated_at or record.created_at
        with session_scope(self.database_url) as session:
            tenant_id = self._tenant_for_workspace(session, record.workspace_id)
            session.merge(
                models.IngestionJob(
                    id=record.job_id,
                    tenant_id=tenant_id,
                    workspace_id=record.workspace_id,
                    document_id=record.document_id,
                    filename=record.filename,
                    status=record.status,
                    progress=record.progress,
                    message=record.message,
                    metadata_json=record.metadata,
                    created_at=record.created_at,
                    updated_at=now,
                )
            )

    def get_ingestion_job(self, job_id: str) -> IngestionJobRecord | None:
        with session_scope(self.database_url) as session:
            row = session.get(models.IngestionJob, job_id)
            return self._ingestion_record(row) if row else None

    def create_chat_session(
        self,
        workspace_id: str,
        title: str | None = None,
        language: str = "auto",
        explanation_level: str = "normal",
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
        with session_scope(self.database_url) as session:
            session.merge(
                models.ChatSession(
                    id=record.session_id,
                    tenant_id=self._tenant_for_workspace(session, workspace_id),
                    workspace_id=workspace_id,
                    title=title,
                    input_language=input_language,
                    response_language=response_language,
                    objective_profile=objective_profile,
                    analysis_mode=analysis_mode,
                    created_at=now,
                    updated_at=now,
                )
            )
        return record

    def get_chat_session(self, session_id: str) -> ChatSessionRecord | None:
        with session_scope(self.database_url) as session:
            row = session.get(models.ChatSession, session_id)
            return self._chat_session_record(row) if row else None

    def list_chat_sessions(self, workspace_id: str, limit: int = 50) -> list[ChatSessionRecord]:
        with session_scope(self.database_url) as session:
            rows = session.execute(
                select(models.ChatSession)
                .where(models.ChatSession.workspace_id == workspace_id)
                .order_by(models.ChatSession.updated_at.desc().nullslast(), models.ChatSession.created_at.desc())
                .limit(limit)
            ).scalars().all()
            return [self._chat_session_record(row) for row in rows]

    def add_chat_message(self, session_id: str, workspace_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> ChatMessageRecord:
        now = datetime.utcnow()
        metadata = metadata or {}
        record = ChatMessageRecord(message_id=str(uuid.uuid4()), session_id=session_id, workspace_id=workspace_id, role=role, content=content, language=metadata.get("language", "auto"), created_at=now, metadata=metadata)
        with session_scope(self.database_url) as session:
            session.add(
                models.ChatMessage(
                    id=record.message_id,
                    tenant_id=self._tenant_for_workspace(session, workspace_id),
                    workspace_id=workspace_id,
                    session_id=session_id,
                    role=role,
                    content=content,
                    language=metadata.get("language", "auto"),
                    metadata_json=metadata,
                    created_at=now,
                )
            )
            chat = session.get(models.ChatSession, session_id)
            if chat:
                chat.updated_at = now
                if role == "user" and not chat.title:
                    chat.title = content[:80]
        return record

    def list_chat_messages(self, session_id: str, limit: int = 50) -> list[ChatMessageRecord]:
        with session_scope(self.database_url) as session:
            rows = session.execute(
                select(models.ChatMessage).where(models.ChatMessage.session_id == session_id).order_by(models.ChatMessage.created_at.asc()).limit(limit)
            ).scalars().all()
            return [self._chat_message_record(row) for row in rows]

    def upsert_memory(self, record: MemoryRecordSchema) -> None:
        with session_scope(self.database_url) as session:
            session.merge(
                models.MemoryRecord(
                    id=record.memory_id,
                    tenant_id=self._tenant_for_workspace(session, record.workspace_id),
                    workspace_id=record.workspace_id,
                    session_id=record.session_id,
                    user_id=record.user_id,
                    objective_profile=record.objective_profile,
                    memory_type=record.memory_type,
                    content=record.content,
                    language=record.metadata.get("language", "auto"),
                    entities_json=record.entities,
                    metadata_json=record.metadata,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )

    def list_memory(self, session_id: str, limit: int = 20) -> list[MemoryRecordSchema]:
        with session_scope(self.database_url) as session:
            rows = session.execute(
                select(models.MemoryRecord).where(models.MemoryRecord.session_id == session_id).order_by(models.MemoryRecord.created_at.desc()).limit(limit)
            ).scalars().all()
            return [self._memory_record(row) for row in reversed(rows)]

    def list_workspace_memory(self, workspace_id: str, objective_profile: str | None = None, memory_type: str | None = None, limit: int = 50) -> list[MemoryRecordSchema]:
        with session_scope(self.database_url) as session:
            stmt = select(models.MemoryRecord).where(models.MemoryRecord.workspace_id == workspace_id)
            if objective_profile:
                stmt = stmt.where(models.MemoryRecord.objective_profile == objective_profile)
            if memory_type:
                stmt = stmt.where(models.MemoryRecord.memory_type == memory_type)
            rows = session.execute(stmt.order_by(models.MemoryRecord.created_at.desc()).limit(limit)).scalars().all()
            return [self._memory_record(row) for row in rows]

    def upsert_extracted_artifact(self, artifact: ExtractedArtifactRecord) -> None:
        with session_scope(self.database_url) as session:
            session.merge(
                models.ExtractedArtifact(
                    id=artifact.artifact_id,
                    tenant_id=self._tenant_for_workspace(session, artifact.workspace_id),
                    workspace_id=artifact.workspace_id,
                    document_id=artifact.document_id,
                    artifact_type=artifact.artifact_type,
                    page_number=artifact.page_number,
                    title=artifact.title,
                    text=artifact.text,
                    data_json=artifact.data,
                    bbox_json=artifact.bbox,
                    created_at=artifact.created_at,
                )
            )

    def upsert_evidence_anchor(self, anchor: EvidenceAnchorRecord) -> None:
        with session_scope(self.database_url) as session:
            session.merge(
                models.EvidenceAnchor(
                    id=anchor.anchor_id,
                    tenant_id=self._tenant_for_workspace(session, anchor.workspace_id),
                    workspace_id=anchor.workspace_id,
                    document_id=anchor.document_id,
                    chunk_id=anchor.chunk_id,
                    artifact_id=anchor.artifact_id,
                    anchor_type=anchor.anchor_type,
                    page_number=anchor.page_number,
                    bbox_json=anchor.bbox,
                    preview_uri=anchor.preview_path,
                    crop_uri=anchor.crop_path,
                    citation_text=anchor.citation_text,
                    metadata_json=anchor.metadata,
                    created_at=anchor.created_at,
                )
            )

    def get_evidence_anchor(self, anchor_id: str) -> EvidenceAnchorRecord | None:
        with session_scope(self.database_url) as session:
            row = session.get(models.EvidenceAnchor, anchor_id)
            return self._evidence_anchor_record(row) if row else None

    def list_evidence_anchors(self, document_id: str | None = None, workspace_id: str | None = None, anchor_type: str | None = None) -> list[EvidenceAnchorRecord]:
        with session_scope(self.database_url) as session:
            stmt = select(models.EvidenceAnchor)
            if document_id:
                stmt = stmt.where(models.EvidenceAnchor.document_id == document_id)
            if workspace_id:
                stmt = stmt.where(models.EvidenceAnchor.workspace_id == workspace_id)
            if anchor_type:
                stmt = stmt.where(models.EvidenceAnchor.anchor_type == anchor_type)
            rows = session.execute(stmt.order_by(models.EvidenceAnchor.page_number.asc())).scalars().all()
            return [self._evidence_anchor_record(row) for row in rows]

    def list_extracted_artifacts(self, document_id: str, artifact_type: str | None = None) -> list[ExtractedArtifactRecord]:
        with session_scope(self.database_url) as session:
            stmt = select(models.ExtractedArtifact).where(models.ExtractedArtifact.document_id == document_id)
            if artifact_type:
                stmt = stmt.where(models.ExtractedArtifact.artifact_type == artifact_type)
            rows = session.execute(stmt.order_by(models.ExtractedArtifact.page_number.asc())).scalars().all()
            return [self._artifact_record(row) for row in rows]

    def log_agent_run(self, run: AgentRunRecord) -> None:
        with session_scope(self.database_url) as session:
            tenant_id = self._tenant_for_workspace(session, run.workspace_id)
            session.merge(
                models.AgentRun(
                    id=run.run_id,
                    tenant_id=tenant_id,
                    workspace_id=run.workspace_id,
                    session_id=run.session_id,
                    objective_profile=run.objective_profile,
                    analysis_mode=run.analysis_mode,
                    status="completed",
                    input_json={},
                    output_json={"steps": [step.model_dump(mode="json") for step in run.steps]},
                    metadata_json=run.metadata,
                    created_at=run.created_at,
                    updated_at=run.created_at,
                )
            )
            for step in run.steps:
                session.merge(
                    models.AgentStep(
                        id=step.step_id,
                        agent_run_id=run.run_id,
                        tenant_id=tenant_id,
                        workspace_id=run.workspace_id,
                        agent_name=step.agent_name,
                        action=step.action,
                        status=step.status,
                        input_json={"summary": step.input_summary},
                        output_json={"summary": step.output_summary, "metadata": step.metadata},
                        tool_calls_json=[],
                        error=None,
                        started_at=run.created_at,
                        completed_at=run.created_at,
                    )
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
        payload = dict(record.metadata)
        if record.actor_email:
            payload["actor_email"] = record.actor_email
        with session_scope(self.database_url) as session:
            session.add(
                models.AuditLog(
                    id=record.audit_id,
                    tenant_id=record.tenant_id,
                    workspace_id=record.workspace_id,
                    user_id=record.user_id,
                    event_type=record.event_type,
                    resource_type=record.resource_type,
                    resource_id=record.resource_id,
                    status=record.status,
                    message=record.message,
                    metadata_json=payload,
                    created_at=record.created_at,
                )
            )
        return record

    def list_audit_logs(self, *, tenant_id: str | None = None, workspace_id: str | None = None, limit: int = 100) -> list[AuditLogRecord]:
        with session_scope(self.database_url) as session:
            stmt = select(models.AuditLog)
            if tenant_id:
                stmt = stmt.where(models.AuditLog.tenant_id == tenant_id)
            if workspace_id:
                stmt = stmt.where(models.AuditLog.workspace_id == workspace_id)
            rows = session.execute(stmt.order_by(models.AuditLog.created_at.desc()).limit(limit)).scalars().all()
            return [self._audit_record(row) for row in rows]

    def upsert_document(self, record: DocumentRecord) -> None:
        with session_scope(self.database_url) as session:
            session.merge(
                models.Document(
                    id=record.document_id,
                    tenant_id=self._tenant_for_workspace(session, record.workspace_id),
                    workspace_id=record.workspace_id,
                    filename=record.filename,
                    source_uri=record.source_path,
                    fingerprint=record.fingerprint,
                    status=record.status,
                    page_count=record.page_count,
                    metadata_json=record.metadata,
                    created_at=record.ingested_at,
                    updated_at=record.updated_at,
                )
            )

    def insert_chunks(self, chunks: list[ChunkRecord]) -> None:
        with session_scope(self.database_url) as session:
            for chunk in chunks:
                metadata = {
                    **chunk.metadata,
                    "chunk_position": chunk.chunk_position,
                    "prev_chunk_id": chunk.prev_chunk_id,
                    "next_chunk_id": chunk.next_chunk_id,
                    "content_type": chunk.content_type,
                    "bbox": chunk.bbox,
                    "section_path": chunk.section_path,
                    "visual_caption": chunk.visual_caption,
                    "table_json": chunk.table_json,
                    "chart_series": chunk.chart_series,
                    "risk_tags": chunk.risk_tags,
                }
                session.merge(
                    models.Chunk(
                        id=chunk.chunk_id,
                        tenant_id=self._tenant_for_workspace(session, chunk.workspace_id),
                        workspace_id=chunk.workspace_id,
                        document_id=chunk.document_id,
                        filename=chunk.filename,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        section=chunk.section,
                        token_count=chunk.token_count,
                        metadata_json=metadata,
                    )
                )

    def list_documents(self, workspace_id: str | None = None) -> list[DocumentRecord]:
        with session_scope(self.database_url) as session:
            stmt = select(models.Document)
            if workspace_id:
                stmt = stmt.where(models.Document.workspace_id == workspace_id)
            rows = session.execute(stmt.order_by(models.Document.created_at.desc())).scalars().all()
            return [self._document_record(row) for row in rows]

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
        return {"status_repaired": repaired_status, "fingerprint_repaired": repaired_fingerprint, "updated_at_repaired": repaired_updated_at}

    def get_document_by_fingerprint(self, fingerprint: str, workspace_id: str = "default") -> DocumentRecord | None:
        with session_scope(self.database_url) as session:
            row = session.execute(
                select(models.Document)
                .where(models.Document.fingerprint == fingerprint, models.Document.workspace_id == workspace_id)
                .order_by(models.Document.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            return self._document_record(row) if row else None

    def get_document(self, document_id: str, workspace_id: str | None = None) -> DocumentRecord | None:
        with session_scope(self.database_url) as session:
            stmt = select(models.Document).where(models.Document.id == document_id)
            if workspace_id:
                stmt = stmt.where(models.Document.workspace_id == workspace_id)
            row = session.execute(stmt).scalar_one_or_none()
            return self._document_record(row) if row else None

    def get_chunk(self, chunk_id: str) -> ChunkRecord | None:
        with session_scope(self.database_url) as session:
            row = session.get(models.Chunk, chunk_id)
            return self._chunk_record(row) if row else None

    def get_chunks(self, chunk_ids: list[str], workspace_id: str | None = None, document_ids: list[str] | None = None) -> list[ChunkRecord]:
        if not chunk_ids:
            return []
        with session_scope(self.database_url) as session:
            stmt = select(models.Chunk).where(models.Chunk.id.in_(chunk_ids))
            if workspace_id:
                stmt = stmt.where(models.Chunk.workspace_id == workspace_id)
            if document_ids:
                stmt = stmt.where(models.Chunk.document_id.in_(document_ids))
            rows = session.execute(stmt).scalars().all()
            by_id = {row.id: self._chunk_record(row) for row in rows}
            return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    def list_chunks(self, document_id: str | None = None, workspace_id: str | None = None) -> list[ChunkRecord]:
        with session_scope(self.database_url) as session:
            stmt = select(models.Chunk)
            if document_id:
                stmt = stmt.where(models.Chunk.document_id == document_id)
            elif workspace_id:
                stmt = stmt.where(models.Chunk.workspace_id == workspace_id)
            rows = session.execute(stmt.order_by(models.Chunk.page_number.asc(), models.Chunk.id.asc())).scalars().all()
            return [self._chunk_record(row) for row in rows]

    def chunk_count(self) -> int:
        with session_scope(self.database_url) as session:
            return int(session.execute(select(func.count()).select_from(models.Chunk)).scalar_one())

    def has_chunks_for_document(self, document_id: str) -> bool:
        with session_scope(self.database_url) as session:
            count = session.execute(select(func.count()).select_from(models.Chunk).where(models.Chunk.document_id == document_id)).scalar_one()
            return bool(int(count))

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        with session_scope(self.database_url) as session:
            session.execute(delete(models.Chunk).where(models.Chunk.id.in_(chunk_ids)))

    def delete_document(self, document_id: str, workspace_id: str) -> list[str]:
        chunk_ids = [chunk.chunk_id for chunk in self.list_chunks(document_id=document_id)]
        with session_scope(self.database_url) as session:
            session.execute(delete(models.Chunk).where(models.Chunk.document_id == document_id, models.Chunk.workspace_id == workspace_id))
            session.execute(delete(models.Document).where(models.Document.id == document_id, models.Document.workspace_id == workspace_id))
        return chunk_ids

    def log_query(self, query_id: str, payload: dict[str, Any]) -> None:
        with session_scope(self.database_url) as session:
            session.merge(models.QueryLog(id=query_id, tenant_id=payload.get("tenant_id", "default-tenant"), workspace_id=payload.get("workspace_id"), session_id=payload.get("session_id"), payload_json=payload, created_at=datetime.utcnow()))

    def recent_query_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with session_scope(self.database_url) as session:
            rows = session.execute(select(models.QueryLog).order_by(models.QueryLog.created_at.desc()).limit(limit)).scalars().all()
            return [row.payload_json for row in rows]

    def upsert_purge_job(self, record: PurgeJobRecord) -> None:
        workspace = self.get_workspace(record.workspace_id)
        tenant_id = workspace.tenant_id if workspace else "default-tenant"
        with session_scope(self.database_url) as session:
            session.merge(
                models.PurgeJob(
                    id=record.purge_job_id,
                    tenant_id=tenant_id,
                    workspace_id=record.workspace_id,
                    document_id=record.document_id,
                    status=record.status,
                    reason=record.reason,
                    requested_by=record.requested_by,
                    receipt_json=record.receipt,
                    error=record.error,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )

    def list_purge_jobs(self, workspace_id: str, limit: int = 50) -> list[PurgeJobRecord]:
        with session_scope(self.database_url) as session:
            rows = session.execute(
                select(models.PurgeJob).where(models.PurgeJob.workspace_id == workspace_id).order_by(models.PurgeJob.created_at.desc()).limit(limit)
            ).scalars().all()
            return [
                PurgeJobRecord(
                    purge_job_id=row.id,
                    workspace_id=row.workspace_id,
                    document_id=row.document_id,
                    status=row.status,
                    reason=row.reason,
                    requested_by=row.requested_by or "system",
                    receipt=row.receipt_json or {},
                    error=row.error,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    def create_deletion_request(self, record: DeletionRequestRecord) -> DeletionRequestRecord:
        with session_scope(self.database_url) as session:
            session.add(models.DeletionRequest(id=record.request_id, tenant_id=record.tenant_id, workspace_id=record.workspace_id, document_id=record.document_id, requested_by=record.requested_by, reason=record.reason, status=record.status, approved_by=record.approved_by, metadata_json=record.metadata, created_at=record.created_at, updated_at=record.updated_at))
        return record

    def list_deletion_requests(self, workspace_id: str, limit: int = 100) -> list[DeletionRequestRecord]:
        with session_scope(self.database_url) as session:
            rows = session.execute(select(models.DeletionRequest).where(models.DeletionRequest.workspace_id == workspace_id).order_by(models.DeletionRequest.created_at.desc()).limit(limit)).scalars().all()
            return [self._deletion_request_record(row) for row in rows]

    def get_deletion_request(self, request_id: str, workspace_id: str | None = None) -> DeletionRequestRecord | None:
        with session_scope(self.database_url) as session:
            stmt = select(models.DeletionRequest).where(models.DeletionRequest.id == request_id)
            if workspace_id:
                stmt = stmt.where(models.DeletionRequest.workspace_id == workspace_id)
            row = session.execute(stmt).scalar_one_or_none()
            return self._deletion_request_record(row) if row else None

    def update_deletion_request(self, request_id: str, *, status: str, approved_by: str | None = None) -> DeletionRequestRecord | None:
        with session_scope(self.database_url) as session:
            row = session.get(models.DeletionRequest, request_id)
            if row is None:
                return None
            row.status = status
            if approved_by:
                row.approved_by = approved_by
            row.updated_at = datetime.utcnow()
        return self.get_deletion_request(request_id)

    @staticmethod
    def _deletion_request_record(row: models.DeletionRequest) -> DeletionRequestRecord:
        return DeletionRequestRecord(request_id=row.id, tenant_id=row.tenant_id, workspace_id=row.workspace_id, document_id=row.document_id, requested_by=row.requested_by, reason=row.reason, status=row.status, approved_by=row.approved_by, created_at=row.created_at, updated_at=row.updated_at, metadata=row.metadata_json or {})

    def log_evaluation_run(self, run_id: str, payload: dict[str, Any]) -> None:
        with session_scope(self.database_url) as session:
            session.merge(models.EvaluationRun(id=run_id, tenant_id=payload.get("tenant_id", "default-tenant"), workspace_id=payload.get("workspace_id"), status=payload.get("status", "completed"), dataset_path=payload.get("dataset_path"), metrics_json=payload.get("metrics", {}), payload_json=payload, created_at=datetime.utcnow()))

    def list_evaluation_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with session_scope(self.database_url) as session:
            rows = session.execute(select(models.EvaluationRun).order_by(models.EvaluationRun.created_at.desc()).limit(limit)).scalars().all()
            return [row.payload_json for row in rows]

    @staticmethod
    def _workspace_record(row: models.Workspace) -> WorkspaceRecord:
        return WorkspaceRecord(workspace_id=row.id, name=row.name, owner_id=row.owner_id, tenant_id=row.tenant_id, private_mode=row.private_mode, external_ai_allowed=row.external_ai_allowed, created_at=row.created_at, updated_at=row.updated_at, metadata=row.metadata_json or {})

    def _user_record(self, session, row: models.User, preferences: dict[str, Any] | None = None) -> UserRecord:
        prefs = preferences or self._preferences_for_user(session, row)
        return UserRecord(
            user_id=row.id,
            tenant_id=row.tenant_id,
            email=row.email,
            display_name=row.display_name,
            avatar_url=row.avatar_url,
            auth_provider=row.auth_provider,
            provider_subject=row.provider_subject,
            status=row.status,
            last_login_at=row.last_login_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            preferences=prefs,
        )

    @staticmethod
    def _api_key_record(row: models.ApiKey) -> ApiKeyRecord:
        return ApiKeyRecord(
            key_id=row.id,
            workspace_id=row.workspace_id,
            name=row.name,
            masked_key=row.masked_key,
            role=row.role,
            permissions=row.permissions_json or [],
            created_by=row.created_by,
            created_at=row.created_at,
            expires_at=row.expires_at,
            last_used_at=row.last_used_at,
            revoked_at=row.revoked_at,
        )

    @staticmethod
    def _invitation_record(row: models.WorkspaceInvitation) -> WorkspaceInvitationRecord:
        status = row.status
        if status == "pending" and row.expires_at <= datetime.utcnow():
            status = "expired"
        return WorkspaceInvitationRecord(
            invitation_id=row.id,
            tenant_id=row.tenant_id,
            workspace_id=row.workspace_id,
            email=row.email,
            role=row.role,
            invited_by=row.invited_by,
            status=status,  # type: ignore[arg-type]
            expires_at=row.expires_at,
            accepted_at=row.accepted_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _preferences_for_user(session, user: models.User) -> dict[str, Any]:
        pref = session.get(models.UserPreference, user.id)
        preferences = dict(pref.metadata_json or {}) if pref else {}
        if user.password_hash:
            preferences["password_hash"] = user.password_hash
        if user.password_salt:
            preferences["password_salt"] = user.password_salt
        preferences["email_verified"] = user.email_verified
        return preferences

    @staticmethod
    def _ingestion_record(row: models.IngestionJob) -> IngestionJobRecord:
        return IngestionJobRecord(job_id=row.id, workspace_id=row.workspace_id, filename=row.filename, status=row.status, progress=row.progress, document_id=row.document_id, message=row.message, created_at=row.created_at, updated_at=row.updated_at, metadata=row.metadata_json or {})

    @staticmethod
    def _chat_session_record(row: models.ChatSession) -> ChatSessionRecord:
        return ChatSessionRecord(session_id=row.id, workspace_id=row.workspace_id, title=row.title, language=row.response_language or row.input_language, input_language=row.input_language, response_language=row.response_language, explanation_level="normal", objective_profile=row.objective_profile, analysis_mode=row.analysis_mode, created_at=row.created_at, updated_at=row.updated_at)

    @staticmethod
    def _chat_message_record(row: models.ChatMessage) -> ChatMessageRecord:
        return ChatMessageRecord(message_id=row.id, session_id=row.session_id, workspace_id=row.workspace_id, role=row.role, content=row.content, language=row.language, created_at=row.created_at, metadata=row.metadata_json or {})

    @staticmethod
    def _memory_record(row: models.MemoryRecord) -> MemoryRecordSchema:
        return MemoryRecordSchema(memory_id=row.id, session_id=row.session_id, workspace_id=row.workspace_id, user_id=row.user_id, objective_profile=row.objective_profile, memory_type=row.memory_type, content=row.content, entities=row.entities_json or [], metadata=row.metadata_json or {}, created_at=row.created_at, updated_at=row.updated_at)

    @staticmethod
    def _evidence_anchor_record(row: models.EvidenceAnchor) -> EvidenceAnchorRecord:
        return EvidenceAnchorRecord(anchor_id=row.id, document_id=row.document_id, workspace_id=row.workspace_id, chunk_id=row.chunk_id, artifact_id=row.artifact_id, anchor_type=row.anchor_type, page_number=row.page_number, bbox=row.bbox_json, preview_path=row.preview_uri, crop_path=row.crop_uri, citation_text=row.citation_text, metadata=row.metadata_json or {}, created_at=row.created_at)

    @staticmethod
    def _artifact_record(row: models.ExtractedArtifact) -> ExtractedArtifactRecord:
        return ExtractedArtifactRecord(artifact_id=row.id, document_id=row.document_id, workspace_id=row.workspace_id, artifact_type=row.artifact_type, page_number=row.page_number, title=row.title, text=row.text, data=row.data_json or {}, bbox=row.bbox_json, created_at=row.created_at)

    @staticmethod
    def _audit_record(row: models.AuditLog) -> AuditLogRecord:
        metadata = dict(row.metadata_json or {})
        actor_email = metadata.pop("actor_email", None)
        return AuditLogRecord(audit_id=row.id, tenant_id=row.tenant_id, workspace_id=row.workspace_id, user_id=row.user_id or "local-user", event_type=row.event_type, actor_email=actor_email, resource_type=row.resource_type, resource_id=row.resource_id, status=row.status, message=row.message, metadata=metadata, created_at=row.created_at)

    @staticmethod
    def _document_record(row: models.Document) -> DocumentRecord:
        return DocumentRecord(document_id=row.id, workspace_id=row.workspace_id, filename=row.filename, source_path=row.source_uri, fingerprint=row.fingerprint or "", status=row.status, page_count=row.page_count, ingested_at=row.created_at, updated_at=row.updated_at, metadata=row.metadata_json or {})

    @staticmethod
    def _chunk_record(row: models.Chunk) -> ChunkRecord:
        metadata = dict(row.metadata_json or {})
        return ChunkRecord(
            chunk_id=row.id,
            document_id=row.document_id,
            workspace_id=row.workspace_id,
            filename=row.filename,
            page_number=row.page_number,
            text=row.text,
            section=row.section,
            token_count=row.token_count,
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
    def _tenant_for_workspace(session, workspace_id: str) -> str:
        workspace = session.get(models.Workspace, workspace_id)
        return workspace.tenant_id if workspace else "default-tenant"

    @staticmethod
    def _ensure_tenant(session, tenant_id: str) -> None:
        if session.get(models.Tenant, tenant_id) is None:
            now = datetime.utcnow()
            session.add(models.Tenant(id=tenant_id, name=tenant_id, plan="free", created_at=now, updated_at=now, metadata_json={}))

    @staticmethod
    def _ensure_user(session, user_id: str, tenant_id: str) -> None:
        if session.get(models.User, user_id) is None:
            now = datetime.utcnow()
            session.add(
                models.User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=f"{user_id}@aiwana.local",
                    display_name=user_id,
                    status="active",
                    auth_provider="system",
                    created_at=now,
                    updated_at=now,
                    metadata_json={},
                )
            )
            session.add(models.UserPreference(user_id=user_id, metadata_json={}))

    @staticmethod
    def _ensure_workspace_member(session, workspace_id: str, user_id: str, tenant_id: str, role_name: str) -> None:
        now = datetime.utcnow()
        role_id = f"{tenant_id}:{role_name}"
        if session.get(models.Role, role_id) is None:
            session.add(models.Role(id=role_id, tenant_id=tenant_id, name=role_name, created_at=now, updated_at=now))
            session.flush()
        session.merge(models.WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role_id=role_id, status="active", joined_at=now, created_at=now, updated_at=now))

    @staticmethod
    def _fingerprint_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def json_type():
    return JSON().with_variant(JSONB, "postgresql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(64), default="free", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    auth_provider: Mapped[str] = mapped_column(String(64), default="local", nullable=False)
    provider_subject: Mapped[str | None] = mapped_column(String(255), index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    password_salt: Mapped[str | None] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    response_language: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    ui_language: Mapped[str] = mapped_column(String(32), default="english", nullable=False)
    default_objective: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    permission_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[str] = mapped_column(String(64), ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[str] = mapped_column(String(64), ForeignKey("permissions.id"), primary_key=True)


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    private_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    external_ai_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(64), ForeignKey("roles.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class WorkspaceInvitation(Base, TimestampMixin):
    __tablename__ = "workspace_invitations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    invited_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("workspace_id", "email", "status", name="uq_workspace_invitation_status"),)


class AuthSession(Base, TimestampMixin):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuthActionToken(Base, TimestampMixin):
    __tablename__ = "auth_action_tokens"
    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    masked_key: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    permissions_json: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="processing", nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class IngestionJob(Base, TimestampMixin):
    __tablename__ = "ingestion_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("documents.id"))
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    input_language: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    response_language: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    objective_profile: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    analysis_mode: Mapped[str] = mapped_column(String(32), default="quick", nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("chat_sessions.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class MemoryRecord(Base, TimestampMixin):
    __tablename__ = "memory_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True, nullable=False)
    objective_profile: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    entities_json: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class ExtractedArtifact(Base):
    __tablename__ = "extracted_artifacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), index=True, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    bbox_json: Mapped[list | None] = mapped_column(json_type())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class EvidenceAnchor(Base):
    __tablename__ = "evidence_anchors"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), index=True, nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("chunks.id"))
    artifact_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("extracted_artifacts.id"))
    anchor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_json: Mapped[list | None] = mapped_column(json_type())
    preview_uri: Mapped[str | None] = mapped_column(Text)
    crop_uri: Mapped[str | None] = mapped_column(Text)
    citation_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    objective_profile: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    analysis_mode: Mapped[str] = mapped_column(String(32), default="quick", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    input_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    output_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    steps: Mapped[list["AgentStep"]] = relationship(back_populates="run")


class AgentStep(Base):
    __tablename__ = "agent_steps"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_runs.id"), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    output_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    tool_calls_json: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    run: Mapped[AgentRun] = relationship(back_populates="steps")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="success", nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Quota(Base):
    __tablename__ = "quotas"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True)
    quota_type: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False)
    used_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "workspace_id", "quota_type", "period", name="uq_quota_scope"),)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    units: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class QueryLog(Base):
    __tablename__ = "query_logs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PurgeJob(Base):
    __tablename__ = "purge_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"))
    receipt_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class DeletionRequest(Base, TimestampMixin):
    __tablename__ = "deletion_requests"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), index=True, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"))
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, default="default-tenant", nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    dataset_path: Mapped[str | None] = mapped_column(Text)
    metrics_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    payload_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class GraphEntity(Base, TimestampMixin):
    __tablename__ = "graph_entities"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    aliases_json: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    properties_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "workspace_id", "entity_type", "canonical_name", name="uq_graph_entity_scope"),)


class GraphRelationship(Base, TimestampMixin):
    __tablename__ = "graph_relationships"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), index=True, nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(64), ForeignKey("graph_entities.id"), index=True, nullable=False)
    target_entity_id: Mapped[str] = mapped_column(String(64), ForeignKey("graph_entities.id"), index=True, nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    properties_json: Mapped[dict] = mapped_column(json_type(), default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class DocumentEntity(Base):
    __tablename__ = "document_entities"
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(64), ForeignKey("graph_entities.id"), primary_key=True)
    evidence_anchor_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("evidence_anchors.id"))
    page_number: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class MemoryEntity(Base):
    __tablename__ = "memory_entities"
    memory_id: Mapped[str] = mapped_column(String(64), ForeignKey("memory_records.id"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(64), ForeignKey("graph_entities.id"), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

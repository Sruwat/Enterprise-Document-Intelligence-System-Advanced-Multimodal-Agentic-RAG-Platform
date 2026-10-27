"""enterprise security foundations

Revision ID: 0002_enterprise_security_foundations
Revises: 0001_initial_production_schema
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_enterprise_security_foundations"
down_revision = "0001_initial_production_schema"
branch_labels = None
depends_on = None


TENANT_TABLES = [
    "documents",
    "chunks",
    "chat_sessions",
    "chat_messages",
    "memory_records",
    "extracted_artifacts",
    "evidence_anchors",
    "agent_runs",
    "agent_steps",
    "audit_logs",
    "query_logs",
    "evaluation_runs",
    "graph_entities",
    "graph_relationships",
    "ingestion_jobs",
    "api_keys",
    "workspaces",
    "workspace_invitations",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    for name, column_type in {
        "avatar_url": sa.Text(),
        "auth_provider": sa.String(length=64),
        "provider_subject": sa.String(length=255),
        "status": sa.String(length=32),
        "last_login_at": sa.DateTime(),
    }.items():
        if name not in user_columns:
            op.add_column("users", sa.Column(name, column_type, nullable=True))
    op.execute("UPDATE users SET auth_provider = COALESCE(auth_provider, 'local'), status = COALESCE(status, 'active')")
    if bind.dialect.name == "postgresql":
        op.alter_column("users", "auth_provider", nullable=False, server_default="local")
        op.alter_column("users", "status", nullable=False, server_default="active")

    member_columns = {column["name"] for column in inspector.get_columns("workspace_members")}
    if "status" not in member_columns:
        op.add_column("workspace_members", sa.Column("status", sa.String(length=32), nullable=True))
    if "joined_at" not in member_columns:
        op.add_column("workspace_members", sa.Column("joined_at", sa.DateTime(), nullable=True))
    if "created_at" not in member_columns:
        op.add_column("workspace_members", sa.Column("created_at", sa.DateTime(), nullable=True))
    if "updated_at" not in member_columns:
        op.add_column("workspace_members", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE workspace_members SET status = COALESCE(status, 'active'), joined_at = COALESCE(joined_at, CURRENT_TIMESTAMP), created_at = COALESCE(created_at, CURRENT_TIMESTAMP)")

    if "workspace_invitations" not in tables:
        op.create_table(
            "workspace_invitations",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(length=64), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
            sa.Column("email", sa.String(length=320), nullable=False, index=True),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("invited_by", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True, index=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("workspace_id", "email", "status", name="uq_workspace_invitation_status"),
        )

    api_columns = {column["name"] for column in inspector.get_columns("api_keys")}
    if "expires_at" not in api_columns:
        op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(), nullable=True))

    op.create_index("ix_users_auth_provider_subject", "users", ["auth_provider", "provider_subject"], unique=False, if_not_exists=True)
    op.create_index("ix_workspace_members_status", "workspace_members", ["workspace_id", "status"], unique=False, if_not_exists=True)

    if bind.dialect.name == "postgresql":
        for table in TENANT_TABLES:
            if table in set(sa.inspect(bind).get_table_names()):
                op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                op.execute(f"DROP POLICY IF EXISTS aiwana_tenant_isolation ON {table}")
                op.execute(
                    f"""
                    CREATE POLICY aiwana_tenant_isolation ON {table}
                    USING (
                        current_setting('app.current_tenant_id', true) = ''
                        OR tenant_id = current_setting('app.current_tenant_id', true)
                    )
                    WITH CHECK (
                        current_setting('app.current_tenant_id', true) = ''
                        OR tenant_id = current_setting('app.current_tenant_id', true)
                    )
                    """
                )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TENANT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS aiwana_tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_workspace_members_status", table_name="workspace_members", if_exists=True)
    op.drop_index("ix_users_auth_provider_subject", table_name="users", if_exists=True)
    op.drop_table("workspace_invitations")
    op.drop_column("api_keys", "expires_at")
    op.drop_column("workspace_members", "updated_at")
    op.drop_column("workspace_members", "created_at")
    op.drop_column("workspace_members", "joined_at")
    op.drop_column("workspace_members", "status")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "status")
    op.drop_column("users", "provider_subject")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "avatar_url")


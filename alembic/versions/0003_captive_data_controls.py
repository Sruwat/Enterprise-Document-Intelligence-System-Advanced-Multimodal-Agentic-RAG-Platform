"""captive data controls

Revision ID: 0003_captive_data_controls
Revises: 0002_enterprise_security_foundations
Create Date: 2026-09-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models import json_type


revision = "0003_captive_data_controls"
down_revision = "0002_enterprise_security_foundations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purge_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("requested_by", sa.String(length=64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("receipt_json", json_type(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_purge_jobs_tenant_id", "purge_jobs", ["tenant_id"])
    op.create_index("ix_purge_jobs_workspace_id", "purge_jobs", ["workspace_id"])
    op.create_index("ix_purge_jobs_document_id", "purge_jobs", ["document_id"])
    op.create_index("ix_purge_jobs_status", "purge_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_purge_jobs_status", table_name="purge_jobs")
    op.drop_index("ix_purge_jobs_document_id", table_name="purge_jobs")
    op.drop_index("ix_purge_jobs_workspace_id", table_name="purge_jobs")
    op.drop_index("ix_purge_jobs_tenant_id", table_name="purge_jobs")
    op.drop_table("purge_jobs")

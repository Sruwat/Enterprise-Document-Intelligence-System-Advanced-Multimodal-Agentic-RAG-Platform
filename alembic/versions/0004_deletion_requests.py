"""persistent deletion approval requests

Revision ID: 0004_deletion_requests
Revises: 0003_captive_data_controls
"""
from alembic import op
import sqlalchemy as sa

from app.db.models import json_type

revision = "0004_deletion_requests"
down_revision = "0003_captive_data_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deletion_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", sa.String(64), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("requested_by", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("approved_by", sa.String(64), sa.ForeignKey("users.id")),
        sa.Column("metadata_json", json_type(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_deletion_requests_tenant_id", "deletion_requests", ["tenant_id"])
    op.create_index("ix_deletion_requests_workspace_id", "deletion_requests", ["workspace_id"])
    op.create_index("ix_deletion_requests_document_id", "deletion_requests", ["document_id"])
    op.create_index("ix_deletion_requests_status", "deletion_requests", ["status"])


def downgrade() -> None:
    for name in ("ix_deletion_requests_status", "ix_deletion_requests_document_id", "ix_deletion_requests_workspace_id", "ix_deletion_requests_tenant_id"):
        op.drop_index(name, table_name="deletion_requests")
    op.drop_table("deletion_requests")

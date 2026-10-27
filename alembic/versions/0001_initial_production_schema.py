"""initial production schema

Revision ID: 0001_initial_production_schema
Revises:
Create Date: 2026-06-01
"""
from alembic import op

from app.db.base import Base
from app.db import models  # noqa: F401

revision = "0001_initial_production_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)


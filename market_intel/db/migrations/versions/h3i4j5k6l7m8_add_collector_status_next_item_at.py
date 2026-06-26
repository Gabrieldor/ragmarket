"""add next_item_at to collector_status

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-06-25

"""
from alembic import op
import sqlalchemy as sa

revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collector_status", sa.Column("next_item_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("collector_status", "next_item_at")

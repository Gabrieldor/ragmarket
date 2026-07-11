"""add modal_429ed to collector_status

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-07-09

"""
from alembic import op
import sqlalchemy as sa

revision = "q2r3s4t5u6v7"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collector_status",
        sa.Column("modal_429ed", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("collector_status", "modal_429ed")

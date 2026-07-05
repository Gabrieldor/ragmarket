"""add required_refine and required_slot to watch_rules

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa

revision = "k7l8m9n0o1p2"
down_revision = "j6k7l8m9n0o1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watch_rules",
        sa.Column("required_refine", sa.Integer(), nullable=True),
    )
    op.add_column(
        "watch_rules",
        sa.Column("required_slot", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("watch_rules", "required_slot")
    op.drop_column("watch_rules", "required_refine")

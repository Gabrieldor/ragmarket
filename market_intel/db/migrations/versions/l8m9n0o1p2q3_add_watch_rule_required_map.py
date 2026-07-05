"""add required_map to watch_rules

Revision ID: l8m9n0o1p2q3
Revises: k7l8m9n0o1p2
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa

revision = "l8m9n0o1p2q3"
down_revision = "k7l8m9n0o1p2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watch_rules",
        sa.Column("required_map", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("watch_rules", "required_map")

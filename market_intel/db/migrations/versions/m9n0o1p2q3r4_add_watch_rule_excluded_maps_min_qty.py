"""add excluded_maps and required_min_qty to watch_rules

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-07-06

"""
from alembic import op
import sqlalchemy as sa

revision = "m9n0o1p2q3r4"
down_revision = "l8m9n0o1p2q3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watch_rules",
        sa.Column("excluded_maps", sa.String(), nullable=True),
    )
    op.add_column(
        "watch_rules",
        sa.Column("required_min_qty", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("watch_rules", "required_min_qty")
    op.drop_column("watch_rules", "excluded_maps")

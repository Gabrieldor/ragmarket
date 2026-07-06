"""add global_excluded_maps to notification_settings

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-07-06

"""
from alembic import op
import sqlalchemy as sa

revision = "n0o1p2q3r4s5"
down_revision = "m9n0o1p2q3r4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_settings",
        sa.Column("global_excluded_maps", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notification_settings", "global_excluded_maps")

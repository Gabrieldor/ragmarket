"""add location_lookup_warning to collector_status

Revision ID: p1q2r3s4t5u6
Revises: n0o1p2q3r4s5
Create Date: 2026-07-08

"""
from alembic import op
import sqlalchemy as sa

revision = "p1q2r3s4t5u6"
down_revision = "n0o1p2q3r4s5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collector_status",
        sa.Column("location_lookup_warning", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("collector_status", "location_lookup_warning")

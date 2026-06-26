"""add collector_config table

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-25

"""
from alembic import op
import sqlalchemy as sa

revision = "g2h3i4j5k6l7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collector_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("item_delay_seconds", sa.Float(), nullable=False, server_default="15.0"),
        sa.Column("location_click_delay_seconds", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO collector_config (id, poll_interval_seconds, item_delay_seconds, "
        "location_click_delay_seconds, updated_at) VALUES (1, 600, 15.0, 2.5, datetime('now'))"
    )


def downgrade() -> None:
    op.drop_table("collector_config")

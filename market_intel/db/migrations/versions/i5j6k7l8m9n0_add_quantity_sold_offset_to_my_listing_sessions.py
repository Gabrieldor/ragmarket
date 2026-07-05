"""add quantity_sold_offset to my_listing_sessions

Revision ID: i5j6k7l8m9n0
Revises: h3i4j5k6l7m8
Create Date: 2026-06-27

"""
from alembic import op
import sqlalchemy as sa

revision = "i5j6k7l8m9n0"
down_revision = "h3i4j5k6l7m8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "my_listing_sessions",
        sa.Column("quantity_sold_offset", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("my_listing_sessions", "quantity_sold_offset")

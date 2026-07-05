"""drop my-sales tracking tables

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa

revision = "j6k7l8m9n0o1"
down_revision = "i5j6k7l8m9n0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("my_sale_events")
    op.drop_table("my_listing_sessions")
    op.drop_table("item_cost_basis")
    op.drop_table("vendor_aliases")


def downgrade() -> None:
    op.create_table(
        "vendor_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alias_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias_name"),
    )
    op.create_table(
        "item_cost_basis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracked_item_id", sa.Integer(), nullable=False),
        sa.Column("cost_per_unit", sa.Float(), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tracked_item_id"], ["tracked_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "my_listing_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracked_item_id", sa.Integer(), nullable=False),
        sa.Column("ssi", sa.String(), nullable=False),
        sa.Column("seller_name", sa.String(), nullable=False),
        sa.Column("shop_name", sa.String(), nullable=True),
        sa.Column("map_name", sa.String(), nullable=True),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("initial_quantity", sa.Integer(), nullable=False),
        sa.Column("last_known_quantity", sa.Integer(), nullable=False),
        sa.Column("total_quantity_sold", sa.Integer(), nullable=False),
        sa.Column("quantity_sold_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("ended_reason", sa.String(), nullable=True),
        sa.Column("cost_per_unit", sa.Float(), nullable=True),
        sa.Column("dismissed", sa.Boolean(), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tracked_item_id"], ["tracked_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tracked_item_id", "ssi", name="uq_my_listing_session"),
    )
    op.create_table(
        "my_sale_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("tracked_item_id", sa.Integer(), nullable=False),
        sa.Column("map_name", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("quantity_sold", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["my_listing_sessions.id"]),
        sa.ForeignKeyConstraint(["tracked_item_id"], ["tracked_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "occurred_at", name="uq_my_sale_event"),
    )

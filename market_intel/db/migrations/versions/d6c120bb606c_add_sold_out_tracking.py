"""add sold out tracking

Revision ID: d6c120bb606c
Revises: 946cab088001
Create Date: 2026-06-24 17:55:08.885505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6c120bb606c'
down_revision: Union[str, Sequence[str], None] = '946cab088001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'tracked_items',
        sa.Column('sold_out_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        'sold_out_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('threshold_ratio', sa.Float(), nullable=False),
        sa.Column('quiet_hours_start', sa.String(), nullable=True),
        sa.Column('quiet_hours_end', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'sold_out_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tracked_item_id', sa.Integer(), nullable=False),
        sa.Column('ssi', sa.String(), nullable=False),
        sa.Column('seller_name', sa.String(), nullable=True),
        sa.Column('shop_name', sa.String(), nullable=True),
        sa.Column('map_name', sa.String(), nullable=True),
        sa.Column('baseline_quantity', sa.Integer(), nullable=False),
        sa.Column('quantity_at_trigger', sa.Integer(), nullable=False),
        sa.Column('threshold_ratio', sa.Float(), nullable=False),
        sa.Column('triggered_at', sa.DateTime(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tracked_item_id'], ['tracked_items.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tracked_item_id', 'ssi', name='uq_sold_out_event'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('sold_out_events')
    op.drop_table('sold_out_config')
    op.drop_column('tracked_items', 'sold_out_enabled')

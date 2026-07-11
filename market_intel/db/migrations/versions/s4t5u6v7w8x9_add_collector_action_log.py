"""add collector_action_log table

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 's4t5u6v7w8x9'
down_revision: Union[str, Sequence[str], None] = 'r3s4t5u6v7w8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'collector_action_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('logged_at', sa.DateTime(), nullable=False),
        sa.Column('tracked_item_id', sa.Integer(), nullable=True),
        sa.Column('item_name', sa.String(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('ssi', sa.String(), nullable=True),
        sa.Column('seller_name', sa.String(), nullable=True),
        sa.Column('shop_name', sa.String(), nullable=True),
        sa.Column('message', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['tracked_item_id'], ['tracked_items.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_collector_action_log_item_time',
        'collector_action_log',
        ['tracked_item_id', 'logged_at'],
    )
    op.create_index(
        'ix_collector_action_log_logged_at',
        'collector_action_log',
        ['logged_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_collector_action_log_logged_at', table_name='collector_action_log')
    op.drop_index('ix_collector_action_log_item_time', table_name='collector_action_log')
    op.drop_table('collector_action_log')

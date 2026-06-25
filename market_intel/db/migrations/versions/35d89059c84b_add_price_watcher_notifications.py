"""add price watcher notifications

Revision ID: 35d89059c84b
Revises: d6c120bb606c
Create Date: 2026-06-24 18:26:02.897278

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '35d89059c84b'
down_revision: Union[str, Sequence[str], None] = 'd6c120bb606c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'watch_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('raw', sa.String(), nullable=False),
        sa.Column('item_name', sa.String(), nullable=False),
        sa.Column('operator', sa.String(), nullable=False),
        sa.Column('target_price', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('state_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_price', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('raw', name='uq_watch_rule_raw'),
    )
    op.create_table(
        'notification_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('watch_rule_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('price', sa.Integer(), nullable=True),
        sa.Column('old_price', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['watch_rule_id'], ['watch_rules.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'notification_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discord_token', sa.String(), nullable=True),
        sa.Column('channel_id', sa.String(), nullable=True),
        sa.Column('user_mention', sa.String(), nullable=False),
        sa.Column('local_sound', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('variance_percent', sa.Float(), nullable=False),
        sa.Column('min_items_below', sa.Integer(), nullable=False),
        sa.Column('rule_delay_seconds', sa.Float(), nullable=False),
        sa.Column('store_type', sa.String(), nullable=False),
        sa.Column('server_type', sa.String(), nullable=False),
        sa.Column('max_pages', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('notification_settings')
    op.drop_table('notification_events')
    op.drop_table('watch_rules')

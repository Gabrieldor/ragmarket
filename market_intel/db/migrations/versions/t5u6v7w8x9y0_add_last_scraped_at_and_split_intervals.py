"""add last_scraped_at to tracked_items, split collector_config poll interval

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't5u6v7w8x9y0'
down_revision: Union[str, Sequence[str], None] = 's4t5u6v7w8x9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'tracked_items',
        sa.Column('last_scraped_at', sa.DateTime(), nullable=True),
    )

    with op.batch_alter_table('collector_config') as batch_op:
        batch_op.add_column(
            sa.Column(
                'registration_interval_seconds',
                sa.Integer(),
                nullable=False,
                server_default='600',
            )
        )
        batch_op.add_column(
            sa.Column(
                'price_watch_interval_seconds',
                sa.Integer(),
                nullable=False,
                server_default='600',
            )
        )
        batch_op.drop_column('poll_interval_seconds')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('collector_config') as batch_op:
        batch_op.add_column(
            sa.Column(
                'poll_interval_seconds',
                sa.Integer(),
                nullable=False,
                server_default='600',
            )
        )
        batch_op.drop_column('price_watch_interval_seconds')
        batch_op.drop_column('registration_interval_seconds')

    op.drop_column('tracked_items', 'last_scraped_at')

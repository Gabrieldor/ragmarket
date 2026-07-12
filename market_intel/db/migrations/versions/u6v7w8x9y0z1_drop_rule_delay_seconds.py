"""drop rule_delay_seconds from notification_settings (superseded by collector_config.item_delay_seconds)

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'u6v7w8x9y0z1'
down_revision: Union[str, Sequence[str], None] = 't5u6v7w8x9y0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('notification_settings') as batch_op:
        batch_op.drop_column('rule_delay_seconds')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('notification_settings') as batch_op:
        batch_op.add_column(
            sa.Column('rule_delay_seconds', sa.Float(), nullable=False, server_default='5.0')
        )

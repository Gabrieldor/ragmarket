"""add watch rule last checked price

Revision ID: d3e255885d87
Revises: 35d89059c84b
Create Date: 2026-06-24 19:20:45.374215

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e255885d87'
down_revision: Union[str, Sequence[str], None] = '35d89059c84b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('watch_rules', sa.Column('last_checked_price', sa.Integer(), nullable=True))
    op.add_column('watch_rules', sa.Column('last_checked_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('watch_rules', 'last_checked_at')
    op.drop_column('watch_rules', 'last_checked_price')

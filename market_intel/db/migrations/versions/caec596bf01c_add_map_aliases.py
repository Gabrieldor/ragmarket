"""add map aliases

Revision ID: caec596bf01c
Revises: d3e255885d87
Create Date: 2026-06-24 19:48:28.299945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'caec596bf01c'
down_revision: Union[str, Sequence[str], None] = 'd3e255885d87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'map_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('raw_map_name', sa.String(), nullable=False),
        sa.Column('canonical_name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('raw_map_name', name='uq_map_alias_raw'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('map_aliases')

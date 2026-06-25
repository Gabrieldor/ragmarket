"""add collector paused flag

Revision ID: a1b2c3d4e5f6
Revises: caec596bf01c
Create Date: 2026-06-25 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'caec596bf01c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('collector_status', sa.Column('paused', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('collector_status', 'paused')

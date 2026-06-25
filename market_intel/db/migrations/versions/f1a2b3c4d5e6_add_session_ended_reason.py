"""add ended_reason to my_listing_sessions

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-06-25

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('my_listing_sessions', sa.Column('ended_reason', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('my_listing_sessions', 'ended_reason')

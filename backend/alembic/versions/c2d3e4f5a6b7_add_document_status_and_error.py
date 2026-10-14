"""add document status and error

Revision ID: c2d3e4f5a6b7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-14 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('status', sa.String(length=50), server_default='stored', nullable=False))
    op.add_column('documents', sa.Column('error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'error')
    op.drop_column('documents', 'status')

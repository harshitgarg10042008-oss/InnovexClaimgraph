"""add delivery rejection fields

Revision ID: a1b2c3d4e5f6
Revises: 2dcc7fe36c94
Create Date: 2026-10-14 06:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '2dcc7fe36c94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add rejection_reason to deliveries (header-level gate-rejection note)
    op.add_column('deliveries', sa.Column('rejection_reason', sa.String(length=500), nullable=True))

    # Add dispatched / accepted / rejected split to delivery_lines
    op.add_column('delivery_lines', sa.Column('dispatched_qty', sa.Numeric(precision=12, scale=3), nullable=True))
    op.add_column('delivery_lines', sa.Column('accepted_qty', sa.Numeric(precision=12, scale=3), nullable=True))
    op.add_column('delivery_lines', sa.Column('rejected_qty', sa.Numeric(precision=12, scale=3), nullable=True))
    op.add_column('delivery_lines', sa.Column('rejection_reason', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('delivery_lines', 'rejection_reason')
    op.drop_column('delivery_lines', 'rejected_qty')
    op.drop_column('delivery_lines', 'accepted_qty')
    op.drop_column('delivery_lines', 'dispatched_qty')
    op.drop_column('deliveries', 'rejection_reason')

"""m5_1_findings_cleanup

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-10-20 20:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: str | None = 'e5f6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add blocks_ready column to findings table
    op.add_column('findings', sa.Column('blocks_ready', sa.Boolean(), server_default='false', nullable=False))

    # 2. Update existing rows with deprecated severity values
    op.execute("UPDATE findings SET severity = 'conflict' WHERE severity = 'blocker'")
    op.execute("UPDATE findings SET severity = 'attention' WHERE severity = 'warn'")

    # 3. Update ck_findings_severity to {info, attention, conflict} only
    op.execute("ALTER TABLE findings DROP CONSTRAINT IF EXISTS ck_findings_severity")
    op.execute("ALTER TABLE findings ADD CONSTRAINT ck_findings_severity CHECK (severity IN ('info', 'attention', 'conflict'))")


def downgrade() -> None:
    # 1. Restore ck_findings_severity to previous set
    op.execute("ALTER TABLE findings DROP CONSTRAINT IF EXISTS ck_findings_severity")
    op.execute("ALTER TABLE findings ADD CONSTRAINT ck_findings_severity CHECK (severity IN ('info', 'warn', 'blocker', 'attention', 'conflict'))")

    # 2. Drop blocks_ready column
    op.drop_column('findings', 'blocks_ready')

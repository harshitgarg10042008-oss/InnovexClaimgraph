"""add_fact_review_fields

Revision ID: 2258242f8e6d
Revises: c2d3e4f5a6b7
Create Date: 2026-10-15 08:03:51.221883

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2258242f8e6d'
down_revision: str | None = 'c2d3e4f5a6b7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop old constraint
    op.execute("ALTER TABLE facts DROP CONSTRAINT IF EXISTS ck_facts_status")
    # Add new constraint with 'not_present' status
    op.execute("ALTER TABLE facts ADD CONSTRAINT ck_facts_status CHECK (status IN ('auto', 'needs_review', 'confirmed', 'edited', 'not_present'))")
    # Add new columns
    op.add_column('facts', sa.Column('original_value_json', postgresql.JSONB(), nullable=True))
    op.add_column('facts', sa.Column('review_note', sa.String(500), nullable=True))


def downgrade() -> None:
    # Drop new columns
    op.drop_column('facts', 'review_note')
    op.drop_column('facts', 'original_value_json')
    # Drop new constraint
    op.execute("ALTER TABLE facts DROP CONSTRAINT IF EXISTS ck_facts_status")
    # Restore old constraint
    op.execute("ALTER TABLE facts ADD CONSTRAINT ck_facts_status CHECK (status IN ('auto', 'needs_review', 'confirmed', 'edited'))")

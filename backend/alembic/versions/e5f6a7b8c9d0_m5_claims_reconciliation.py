"""m5_claims_reconciliation

Revision ID: e5f6a7b8c9d0
Revises: 2258242f8e6d
Create Date: 2026-10-20 18:55:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = '2258242f8e6d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update links constraints and add columns
    op.execute("ALTER TABLE links DROP CONSTRAINT IF EXISTS ck_links_method")
    op.execute("ALTER TABLE links ADD CONSTRAINT ck_links_method CHECK (method IN ('hard_key', 'key', 'fuzzy', 'manual'))")

    op.add_column('links', sa.Column('status', sa.String(length=20), server_default='auto_linked', nullable=False))
    op.execute("ALTER TABLE links ADD CONSTRAINT ck_links_status CHECK (status IN ('auto_linked', 'suggested', 'conflict', 'confirmed', 'rejected'))")
    op.add_column('links', sa.Column('reason', sa.Text(), nullable=True))
    op.add_column('links', sa.Column('evidence_fact_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # 2. Update findings severity constraint and add helper columns
    op.execute("ALTER TABLE findings DROP CONSTRAINT IF EXISTS ck_findings_severity")
    op.execute("ALTER TABLE findings ADD CONSTRAINT ck_findings_severity CHECK (severity IN ('info', 'warn', 'blocker', 'attention', 'conflict'))")
    op.add_column('findings', sa.Column('title', sa.String(length=255), nullable=True))
    op.add_column('findings', sa.Column('explanation_template', sa.Text(), nullable=True))
    op.add_column('findings', sa.Column('computed_numbers', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('findings', sa.Column('needs_human_or_legal_review', sa.Boolean(), server_default='false', nullable=False))

    # 3. Add source fact_id to transaction/entity tables for audit provenance
    op.add_column('invoices', sa.Column('fact_id', sa.UUID(), sa.ForeignKey('facts.id', ondelete='SET NULL'), nullable=True))
    op.add_column('deliveries', sa.Column('fact_id', sa.UUID(), sa.ForeignKey('facts.id', ondelete='SET NULL'), nullable=True))
    op.add_column('purchase_orders', sa.Column('fact_id', sa.UUID(), sa.ForeignKey('facts.id', ondelete='SET NULL'), nullable=True))
    op.add_column('adjustments', sa.Column('fact_id', sa.UUID(), sa.ForeignKey('facts.id', ondelete='SET NULL'), nullable=True))


def downgrade() -> None:
    # Drop provenance fact_id columns
    op.drop_column('adjustments', 'fact_id')
    op.drop_column('purchase_orders', 'fact_id')
    op.drop_column('deliveries', 'fact_id')
    op.drop_column('invoices', 'fact_id')

    # Drop findings columns and restore constraint
    op.drop_column('findings', 'needs_human_or_legal_review')
    op.drop_column('findings', 'computed_numbers')
    op.drop_column('findings', 'explanation_template')
    op.drop_column('findings', 'title')
    op.execute("ALTER TABLE findings DROP CONSTRAINT IF EXISTS ck_findings_severity")
    op.execute("ALTER TABLE findings ADD CONSTRAINT ck_findings_severity CHECK (severity IN ('info', 'warn', 'blocker'))")

    # Drop links columns and restore constraint
    op.execute("ALTER TABLE links DROP CONSTRAINT IF EXISTS ck_links_status")
    op.drop_column('links', 'evidence_fact_ids')
    op.drop_column('links', 'reason')
    op.drop_column('links', 'status')
    op.execute("ALTER TABLE links DROP CONSTRAINT IF EXISTS ck_links_method")
    op.execute("ALTER TABLE links ADD CONSTRAINT ck_links_method CHECK (method IN ('key', 'fuzzy', 'manual'))")

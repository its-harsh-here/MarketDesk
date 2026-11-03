"""research check tracking (M02)

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("dataset", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=True),
        sa.Column("last_checked_at", marketdesk.db.types.UTCDateTime(), nullable=True),
        sa.Column("last_success_at", marketdesk.db.types.UTCDateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("latest_filing_date", sa.Date(), nullable=True),
        sa.Column("latest_accession", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "dataset", name="uq_research_check"),
    )


def downgrade() -> None:
    op.drop_table("research_checks")

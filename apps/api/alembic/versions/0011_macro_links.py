"""Owner-entered company ↔ macro series links (M12)

Additive: one new table.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "macro_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("series_symbol", sa.String(length=32), nullable=False),
        sa.Column("relation", sa.String(length=12), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "series_symbol", name="uq_macro_link"),
    )
    op.create_index(op.f("ix_macro_links_instrument_id"), "macro_links", ["instrument_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_macro_links_instrument_id"), table_name="macro_links")
    op.drop_table("macro_links")

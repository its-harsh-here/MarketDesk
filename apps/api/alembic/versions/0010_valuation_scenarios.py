"""Saved valuation scenarios (M11)

Additive: one new table.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "valuation_scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("case", sa.String(length=8), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "name", name="uq_valuation_scenario_name"),
    )
    op.create_index(op.f("ix_valuation_scenarios_instrument_id"), "valuation_scenarios", ["instrument_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_valuation_scenarios_instrument_id"), table_name="valuation_scenarios")
    op.drop_table("valuation_scenarios")

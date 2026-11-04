"""Allocation targets for rebalance simulations (M09)

Additive: one new table.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allocation_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("target_pct", marketdesk.db.types.DecimalText(), nullable=False),
        sa.Column("updated_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("currency", "symbol", name="uq_allocation_target"),
    )


def downgrade() -> None:
    op.drop_table("allocation_targets")

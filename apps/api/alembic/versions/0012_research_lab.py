"""Research runs and paper portfolios (M13)

Additive: three new tables, isolated from the real ledger.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("rule", sa.String(length=16), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("costs", sa.JSON(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_runs_created_at"), "research_runs", ["created_at"], unique=False)
    op.create_table(
        "paper_portfolios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("starting_cash", marketdesk.db.types.DecimalText(), nullable=False),
        sa.Column("fee_pct", marketdesk.db.types.DecimalText(), nullable=False),
        sa.Column("slippage_bps", marketdesk.db.types.DecimalText(), nullable=False),
        sa.Column("benchmark", sa.String(length=32), nullable=True),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", marketdesk.db.types.DecimalText(), nullable=False),
        sa.Column("placed_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("placed_session", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_paper_orders_portfolio_id"), "paper_orders", ["portfolio_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_paper_orders_portfolio_id"), table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_table("paper_portfolios")
    op.drop_index(op.f("ix_research_runs_created_at"), table_name="research_runs")
    op.drop_table("research_runs")

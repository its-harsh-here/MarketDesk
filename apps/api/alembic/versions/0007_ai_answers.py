"""Grok research answers with evidence, flags, usage and budget fields (M03)

Additive: one new table.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("finished_at", marketdesk.db.types.UTCDateTime(), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=60), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("reserved_usd", marketdesk.db.types.DecimalText(), nullable=True),
        sa.Column("cost_usd", marketdesk.db.types.DecimalText(), nullable=True),
        sa.Column("data_cutoff", marketdesk.db.types.UTCDateTime(), nullable=True),
        sa.Column("reused_from", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_answers_created_at"), "ai_answers", ["created_at"], unique=False)
    op.create_index(op.f("ix_ai_answers_day"), "ai_answers", ["day"], unique=False)
    op.create_index(op.f("ix_ai_answers_evidence_hash"), "ai_answers", ["evidence_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_answers_evidence_hash"), table_name="ai_answers")
    op.drop_index(op.f("ix_ai_answers_day"), table_name="ai_answers")
    op.drop_index(op.f("ix_ai_answers_created_at"), table_name="ai_answers")
    op.drop_table("ai_answers")

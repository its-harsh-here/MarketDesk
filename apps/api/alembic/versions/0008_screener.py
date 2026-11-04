"""Screener universes, saved screens, peer sets and the screening snapshot (M06)

Additive: four new tables; existing data is untouched.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screen_universes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "saved_screens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("universe", sa.JSON(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("sort", sa.JSON(), nullable=True),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "peer_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("peers", sa.JSON(), nullable=False),
        sa.Column("updated_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id"),
    )
    op.create_table(
        "screen_metrics",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("computed_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("instrument_id"),
    )
    op.create_index(op.f("ix_screen_metrics_computed_at"), "screen_metrics", ["computed_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_screen_metrics_computed_at"), table_name="screen_metrics")
    op.drop_table("screen_metrics")
    op.drop_table("peer_sets")
    op.drop_table("saved_screens")
    op.drop_table("screen_universes")

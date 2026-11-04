"""decision journal: structured fields, immutable versions with evidence, reviews (M10)

Additive. Every existing entry gets version 1 holding its current text, marked as recorded before versioning (no
evidence snapshot exists for it); the entry rows themselves are not rewritten.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

PRE_VERSIONING = {
    "captured": False,
    "reason": "Recorded before versioning was introduced; no evidence was captured with this note.",
}


def upgrade() -> None:
    with op.batch_alter_table("journal_entries", schema=None) as batch:
        batch.add_column(sa.Column("decision", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("conviction", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("horizon", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.create_table(
        "journal_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("change_note", sa.String(length=500), nullable=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", "version", name="uq_journal_version"),
    )
    op.create_index(op.f("ix_journal_versions_entry_id"), "journal_versions", ["entry_id"], unique=False)
    op.create_table(
        "journal_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=True),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_journal_reviews_entry_id"), "journal_reviews", ["entry_id"], unique=False)

    # Backfill version 1 from each existing entry (its text as it stands today).
    bind = op.get_bind()
    entries = sa.table(
        "journal_entries",
        sa.column("id", sa.Integer),
        sa.column("entry_date", sa.Date),
        sa.column("title", sa.String),
        sa.column("thesis", sa.Text),
        sa.column("risks", sa.Text),
        sa.column("invalidation", sa.Text),
        sa.column("created_at", marketdesk.db.types.UTCDateTime()),
    )
    versions = sa.table(
        "journal_versions",
        sa.column("entry_id", sa.Integer),
        sa.column("version", sa.Integer),
        sa.column("created_at", marketdesk.db.types.UTCDateTime()),
        sa.column("change_note", sa.String),
        sa.column("content", sa.JSON),
        sa.column("evidence", sa.JSON),
    )
    rows = []
    for e in bind.execute(sa.select(entries)).mappings():
        rows.append(
            {
                "entry_id": e["id"],
                "version": 1,
                "created_at": e["created_at"] or datetime.now(UTC),
                "change_note": "Original note (recorded before versioning).",
                "content": {
                    "entry_date": e["entry_date"].isoformat() if e["entry_date"] else None,
                    "title": e["title"],
                    "thesis": e["thesis"] or "",
                    "risks": e["risks"] or "",
                    "invalidation": e["invalidation"] or "",
                    "decision": None,
                    "conviction": None,
                    "horizon": None,
                },
                "evidence": PRE_VERSIONING,
            }
        )
    if rows:
        op.bulk_insert(versions, rows)


def downgrade() -> None:
    op.drop_index(op.f("ix_journal_reviews_entry_id"), table_name="journal_reviews")
    op.drop_table("journal_reviews")
    op.drop_index(op.f("ix_journal_versions_entry_id"), table_name="journal_versions")
    op.drop_table("journal_versions")
    with op.batch_alter_table("journal_entries", schema=None) as batch:
        batch.drop_column("version")
        batch.drop_column("horizon")
        batch.drop_column("conviction")
        batch.drop_column("decision")

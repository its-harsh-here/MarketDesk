"""alert rules, quiet hours, deliveries and briefings (M05)

Additive: existing alerts become PRICE rules with manual rearm (server default), existing events PRICE events.
Event target/observed prices become nullable because filing events have no price.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("alerts", schema=None) as batch:
        batch.add_column(sa.Column("rule", sa.String(length=16), server_default="PRICE", nullable=False))
        batch.add_column(sa.Column("params", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("cooldown_minutes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rearm_at", marketdesk.db.types.UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("quiet_start", sa.String(length=5), nullable=True))
        batch.add_column(sa.Column("quiet_end", sa.String(length=5), nullable=True))
        batch.add_column(sa.Column("last_skip_reason", sa.String(length=200), nullable=True))
    with op.batch_alter_table("alert_events", schema=None) as batch:
        batch.alter_column("target_price", existing_type=marketdesk.db.types.DecimalText(), nullable=True)
        batch.alter_column("observed_price", existing_type=marketdesk.db.types.DecimalText(), nullable=True)
        batch.add_column(sa.Column("rule", sa.String(length=16), server_default="PRICE", nullable=False))
        batch.add_column(sa.Column("explanation", sa.Text(), nullable=True))
        batch.add_column(sa.Column("link", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("deliver_after", marketdesk.db.types.UTCDateTime(), nullable=True))
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("updated_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["alert_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "channel", name="uq_delivery_event_channel"),
    )
    op.create_index(op.f("ix_alert_deliveries_event_id"), "alert_deliveries", ["event_id"], unique=False)
    op.create_table(
        "briefings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("market", sa.String(length=2), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", marketdesk.db.types.UTCDateTime(), nullable=False),
        sa.Column("read_at", marketdesk.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "market", "session_date", name="uq_briefing_session"),
    )
    op.create_index(op.f("ix_briefings_created_at"), "briefings", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_briefings_created_at"), table_name="briefings")
    op.drop_table("briefings")
    op.drop_index(op.f("ix_alert_deliveries_event_id"), table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
    with op.batch_alter_table("alert_events", schema=None) as batch:
        batch.drop_column("deliver_after")
        batch.drop_column("link")
        batch.drop_column("explanation")
        batch.drop_column("rule")
        batch.alter_column("observed_price", existing_type=marketdesk.db.types.DecimalText(), nullable=False)
        batch.alter_column("target_price", existing_type=marketdesk.db.types.DecimalText(), nullable=False)
    with op.batch_alter_table("alerts", schema=None) as batch:
        batch.drop_column("last_skip_reason")
        batch.drop_column("quiet_end")
        batch.drop_column("quiet_start")
        batch.drop_column("rearm_at")
        batch.drop_column("cooldown_minutes")
        batch.drop_column("params")
        batch.drop_column("rule")

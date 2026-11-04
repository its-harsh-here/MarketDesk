"""USD account and FX conversions (M08)

Additive: the ledger's existing `currency` column becomes the account key (every existing row is INR and stays
byte-identical). New nullable columns describe FX conversions, and the type check admits 'FX'.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

OLD_TYPES = "type IN ('DEPOSIT','WITHDRAWAL','BUY','SELL','DIVIDEND','SPLIT')"
NEW_TYPES = "type IN ('DEPOSIT','WITHDRAWAL','BUY','SELL','DIVIDEND','SPLIT','FX')"


def upgrade() -> None:
    op.execute("UPDATE ledger_transactions SET currency = 'INR' WHERE currency IS NULL")
    with op.batch_alter_table("ledger_transactions", schema=None) as batch:
        batch.add_column(sa.Column("counter_currency", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("counter_amount", marketdesk.db.types.DecimalText(), nullable=True))
        batch.add_column(sa.Column("fx_rate", marketdesk.db.types.DecimalText(), nullable=True))
        batch.add_column(sa.Column("fx_source", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("fx_time", marketdesk.db.types.UTCDateTime(), nullable=True))
        batch.drop_constraint("ck_txn_type", type_="check")
        batch.create_check_constraint("ck_txn_type", NEW_TYPES)


def downgrade() -> None:
    op.execute("DELETE FROM ledger_transactions WHERE type = 'FX'")
    with op.batch_alter_table("ledger_transactions", schema=None) as batch:
        batch.drop_constraint("ck_txn_type", type_="check")
        batch.create_check_constraint("ck_txn_type", OLD_TYPES)
        batch.drop_column("fx_time")
        batch.drop_column("fx_source")
        batch.drop_column("fx_rate")
        batch.drop_column("counter_amount")
        batch.drop_column("counter_currency")

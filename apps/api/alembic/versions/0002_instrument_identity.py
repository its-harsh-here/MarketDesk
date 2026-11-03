"""canonical instrument identity (M01)

Adds listing identity to instruments (provider venue code, ISO 10383 MIC, country, identity source/verification time)
and an instrument_identifiers table for provider/registry mappings. Existing rows keep every value they had; the
backfill only adds information:
- one identifier per instrument for the symbol it already has with its provider (scheme = provider name);
- country/MIC where the stored symbol suffix (.NS/.BO) or stored exchange name maps to exactly one venue.
Backfilled identity is marked unverified (identity_verified_at NULL); the app confirms it from provider metadata the
next time it fetches a quote.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import marketdesk.db.types

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Frozen copies (a migration must not change when application code changes later).
_SUFFIX = {".NS": ("XNSE", "IN", "NSI"), ".BO": ("XBOM", "IN", "BSE")}
_EXCHANGE_NAMES = {
    "NSE": ("XNSE", "IN", "NSI"),
    "BSE": ("XBOM", "IN", "BSE"),
    "NasdaqGS": ("XNAS", "US", "NMS"),
    "NasdaqGM": ("XNAS", "US", "NGM"),
    "NasdaqCM": ("XNAS", "US", "NCM"),
    "NYSE": ("XNYS", "US", "NYQ"),
    "NYSEArca": ("ARCX", "US", "PCX"),
    "NYSE Arca": ("ARCX", "US", "PCX"),
}


def _derive(symbol: str, exchange: str | None):
    for suffix, venue in _SUFFIX.items():
        if symbol.upper().endswith(suffix):
            return venue
    if exchange and exchange in _EXCHANGE_NAMES:
        return _EXCHANGE_NAMES[exchange]
    return None


def upgrade() -> None:
    with op.batch_alter_table("instruments", schema=None) as batch:
        batch.add_column(sa.Column("exchange_code", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("mic", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("country", sa.String(length=2), nullable=True))
        batch.add_column(sa.Column("identity_source", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("identity_verified_at", marketdesk.db.types.UTCDateTime(), nullable=True))
        batch.create_index(batch.f("ix_instruments_country"), ["country"], unique=False)

    op.create_table(
        "instrument_identifiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("scheme", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("verified_at", marketdesk.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "scheme", name="uq_identifier_instrument_scheme"),
    )
    op.create_index("ix_identifier_scheme_value", "instrument_identifiers", ["scheme", "value"], unique=False)

    bind = op.get_bind()
    instruments = sa.table(
        "instruments",
        sa.column("id", sa.Integer),
        sa.column("provider", sa.String),
        sa.column("symbol", sa.String),
        sa.column("exchange", sa.String),
        sa.column("exchange_code", sa.String),
        sa.column("mic", sa.String),
        sa.column("country", sa.String),
        sa.column("identity_source", sa.String),
    )
    identifiers = sa.table(
        "instrument_identifiers",
        sa.column("instrument_id", sa.Integer),
        sa.column("scheme", sa.String),
        sa.column("value", sa.String),
        sa.column("source", sa.String),
    )
    rows = bind.execute(sa.select(instruments.c.id, instruments.c.provider, instruments.c.symbol, instruments.c.exchange))
    for iid, provider, symbol, exchange in rows.fetchall():
        bind.execute(
            identifiers.insert().values(
                instrument_id=iid, scheme=provider, value=symbol, source="migration 0002: existing provider symbol"
            )
        )
        venue = _derive(symbol, exchange)
        if venue is not None:
            mic, country, code = venue
            if symbol.startswith("^"):
                mic = None  # an index has no listing venue
            bind.execute(
                instruments.update()
                .where(instruments.c.id == iid)
                .values(
                    mic=mic,
                    country=country,
                    exchange_code=code,
                    identity_source="migration 0002: derived from stored symbol/exchange (unverified)",
                )
            )


def downgrade() -> None:
    op.drop_index("ix_identifier_scheme_value", table_name="instrument_identifiers")
    op.drop_table("instrument_identifiers")
    with op.batch_alter_table("instruments", schema=None) as batch:
        batch.drop_index(batch.f("ix_instruments_country"))
        batch.drop_column("identity_verified_at")
        batch.drop_column("identity_source")
        batch.drop_column("country")
        batch.drop_column("mic")
        batch.drop_column("exchange_code")

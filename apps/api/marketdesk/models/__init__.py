"""SQLAlchemy ORM models. Money and quantities use DecimalText; timestamps are UTC."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from marketdesk.db.types import DecimalText, UTCDateTime, utcnow


class Base(DeclarativeBase):
    pass


class AppSetting(Base):
    """Key/value user preferences and small runtime state (e.g. fixture replay cursor)."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("provider", "symbol", name="uq_instrument_provider_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    exchange: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str | None] = mapped_column(String(8))
    timezone: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str | None] = mapped_column(String(16))  # EQUITY, INDEX, ETF, FUND, ...
    # Canonical listing identity (migration 0002). Filled from provider metadata; NULL means not yet known.
    exchange_code: Mapped[str | None] = mapped_column(String(16))  # provider's venue code, e.g. Yahoo "NSI"
    mic: Mapped[str | None] = mapped_column(String(8))  # ISO 10383, e.g. XNSE, XNAS
    country: Mapped[str | None] = mapped_column(String(2), index=True)  # ISO 3166-1 alpha-2
    identity_source: Mapped[str | None] = mapped_column(String(64))
    identity_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class InstrumentIdentifier(Base):
    """Provider/registry identifiers for one listing (yahoo symbol now; e.g. SEC CIK or a broker symbol later).

    A value is not assumed to be globally unique across schemes: a CIK, for instance, covers every share class of an
    issuer, so lookups go by (scheme, value) and may return several listings.
    """

    __tablename__ = "instrument_identifiers"
    __table_args__ = (
        UniqueConstraint("instrument_id", "scheme", name="uq_identifier_instrument_scheme"),
        Index("ix_identifier_scheme_value", "scheme", "value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False)
    scheme: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str | None] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Watchlist(Base):
    __tablename__ = "watchlists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    sort_key: Mapped[str] = mapped_column(String(24), default="manual")
    sort_dir: Mapped[str] = mapped_column(String(4), default="asc")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", order_by="WatchlistItem.position"
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "instrument_id", name="uq_watchlist_instrument"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    instrument: Mapped[Instrument] = relationship(lazy="joined")


class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        CheckConstraint("type IN ('DEPOSIT','WITHDRAWAL','BUY','SELL','DIVIDEND','SPLIT')", name="ck_txn_type"),
        Index("ix_txn_effective", "effective_date", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(12), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal | None] = mapped_column(DecimalText)
    price: Mapped[Decimal | None] = mapped_column(DecimalText)
    fees: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    split_from: Mapped[Decimal | None] = mapped_column(DecimalText)
    split_to: Mapped[Decimal | None] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    notes: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | import | sample
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))
    # Immutable creation metadata
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_via: Mapped[str] = mapped_column(String(16), default="api")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    instrument: Mapped[Instrument | None] = relationship(lazy="joined")


class ImportBatch(Base):
    """A previewed CSV import. Confirming is idempotent: a committed batch cannot be committed again."""

    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str | None] = mapped_column(String(200))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(12), default="previewed")  # previewed | committed
    rows: Mapped[list] = mapped_column(JSON)  # normalized valid rows awaiting confirmation
    summary: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (CheckConstraint("direction IN ('ABOVE','BELOW')", name="ck_alert_direction"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), index=True)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)
    target_price: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    note: Mapped[str | None] = mapped_column(String(280))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    arm_seq: Mapped[int] = mapped_column(Integer, default=1)
    armed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_observation_id: Mapped[int | None] = mapped_column(Integer)
    last_observed_price: Mapped[Decimal | None] = mapped_column(DecimalText)
    last_observed_market_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    instrument: Mapped[Instrument] = relationship(lazy="joined")
    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="alert", cascade="all, delete-orphan", order_by="AlertEvent.triggered_at.desc()"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    arm_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_key: Mapped[str] = mapped_column(String(64), unique=True)  # "<alert_id>:<arm_seq>"
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("quote_observations.id", ondelete="SET NULL"))
    direction: Mapped[str] = mapped_column(String(5))
    target_price: Mapped[Decimal] = mapped_column(DecimalText)
    observed_price: Mapped[Decimal] = mapped_column(DecimalText)
    observed_market_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    provider: Mapped[str] = mapped_column(String(16))
    triggered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    alert: Mapped[Alert] = relationship(back_populates="events")


class QuoteObservation(Base):
    """A distinct provider quotation, keyed by market timestamp so re-reading a cached quote is idempotent."""

    __tablename__ = "quote_observations"
    __table_args__ = (UniqueConstraint("instrument_id", "provider", "market_time", name="uq_observation_market_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    price: Mapped[Decimal] = mapped_column(DecimalText)
    market_time: Mapped[datetime] = mapped_column(UTCDateTime)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160))
    thesis: Mapped[str] = mapped_column(Text, default="")
    risks: Mapped[str] = mapped_column(Text, default="")
    invalidation: Mapped[str] = mapped_column(Text, default="")
    review_date: Mapped[date | None] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    instrument: Mapped[Instrument] = relationship(lazy="joined")
    tags: Mapped[list[JournalTag]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", lazy="selectin", order_by="JournalTag.tag"
    )


class JournalTag(Base):
    __tablename__ = "journal_tags"
    __table_args__ = (UniqueConstraint("entry_id", "tag", name="uq_journal_entry_tag"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(40), index=True)

    entry: Mapped[JournalEntry] = relationship(back_populates="tags")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_key: Mapped[str] = mapped_column(String(64), index=True)  # hashed client address
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False)
    attempted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class MarketCacheEntry(Base):
    """Persisted last-known-good provider payloads (bounded; pruned by last access)."""

    __tablename__ = "market_cache"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict | list] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_access_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class WorkerStatus(Base):
    __tablename__ = "worker_status"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_cycle_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(500))
    cycles: Mapped[int] = mapped_column(Integer, default=0)
    last_summary: Mapped[dict | None] = mapped_column(JSON)

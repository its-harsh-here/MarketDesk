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
        CheckConstraint("type IN ('DEPOSIT','WITHDRAWAL','BUY','SELL','DIVIDEND','SPLIT','FX')", name="ck_txn_type"),
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
    # The currency account this row belongs to (INR or USD). Amounts are in this currency; never converted in place.
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    # FX conversions (type FX, migration 0005): `amount` + `fees` leave this account, `counter_amount` arrives in the
    # `counter_currency` account. `fx_rate` is the quoted USD/INR rate (INR per 1 USD), with its source and time.
    counter_currency: Mapped[str | None] = mapped_column(String(8))
    counter_amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    fx_rate: Mapped[Decimal | None] = mapped_column(DecimalText)
    fx_source: Mapped[str | None] = mapped_column(String(80))
    fx_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
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
    # PRICE target / CROSS level, or the multiple for VOLUME and VOLATILITY rules (unused for FILING).
    target_price: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    note: Mapped[str | None] = mapped_column(String(280))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # M05 rule definition (migration 0004). Existing alerts are PRICE rules with manual rearm.
    rule: Mapped[str] = mapped_column(String(16), nullable=False, default="PRICE", server_default="PRICE")
    params: Mapped[dict | None] = mapped_column(JSON)  # e.g. {"lookback": 20} or {"forms": ["10-K", "8-K"]}
    cooldown_minutes: Mapped[int | None] = mapped_column(Integer)  # None = rearm manually
    rearm_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    quiet_start: Mapped[str | None] = mapped_column(String(5))  # "22:00" in the display timezone
    quiet_end: Mapped[str | None] = mapped_column(String(5))
    last_skip_reason: Mapped[str | None] = mapped_column(String(200))
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
    target_price: Mapped[Decimal | None] = mapped_column(DecimalText)
    observed_price: Mapped[Decimal | None] = mapped_column(DecimalText)
    observed_market_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    provider: Mapped[str] = mapped_column(String(16))
    triggered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    rule: Mapped[str] = mapped_column(String(16), nullable=False, default="PRICE", server_default="PRICE")
    explanation: Mapped[str | None] = mapped_column(Text)  # why it fired, with the data and its timestamps
    link: Mapped[str | None] = mapped_column(String(300))  # filing URL for FILING events
    deliver_after: Mapped[datetime | None] = mapped_column(UTCDateTime)  # held during quiet hours

    alert: Mapped[Alert] = relationship(back_populates="events")


class AlertDelivery(Base):
    """One row per event and channel: retries and restarts cannot deliver the same notice twice."""

    __tablename__ = "alert_deliveries"
    __table_args__ = (UniqueConstraint("event_id", "channel", name="uq_delivery_event_channel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("alert_events.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # in_app (external channels when configured)
    status: Mapped[str] = mapped_column(String(12), nullable=False)  # delivered | held | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Briefing(Base):
    """A stored deterministic briefing; one per kind, market and session date (idempotent across restarts)."""

    __tablename__ = "briefings"
    __table_args__ = (UniqueConstraint("kind", "market", "session_date", name="uq_briefing_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # morning | close
    market: Mapped[str] = mapped_column(String(2), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"items": [...], "session": {...}, ...}
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AllocationTarget(Base):
    """The owner's target weight for a holding in one currency account (used only for rebalance simulations)."""

    __tablename__ = "allocation_targets"
    __table_args__ = (UniqueConstraint("currency", "symbol", name="uq_allocation_target"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    target_pct: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ScreenUniverse(Base):
    """A named, user-declared list of symbols the screener may use (bounded; never "the whole market")."""

    __tablename__ = "screen_universes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    symbols: Mapped[list] = mapped_column(JSON, nullable=False)  # provider symbols, in the order given
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SavedScreen(Base):
    __tablename__ = "saved_screens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    universe: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"kind": "watchlist", "id": 3} etc.
    filters: Mapped[list] = mapped_column(JSON, nullable=False)
    sort: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class PeerSet(Base):
    """The owner's chosen peers for an instrument (at most five symbols)."""

    __tablename__ = "peer_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    peers: Mapped[list] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ScreenMetric(Base):
    """The normalized screening snapshot of one instrument: every metric with its value (or null and why), unit,
    source and as-of date. Screens read only these rows; refreshing them is a separate, bounded job."""

    __tablename__ = "screen_metrics"
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    values: Mapped[dict] = mapped_column(JSON, nullable=False)
    errors: Mapped[dict | None] = mapped_column(JSON)  # input kind -> sanitized reason


class AiAnswer(Base):
    """A Grok research answer with the evidence it was given, validation flags, model and usage. Kept for reuse."""

    __tablename__ = "ai_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # UTC day, for the daily budget
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # ask | results | catalysts | compare
    symbols: Mapped[list] = mapped_column(JSON, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False)  # running | done | reused | refused | failed
    steps: Mapped[list | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(60))
    output: Mapped[dict | None] = mapped_column(JSON)
    sources: Mapped[list | None] = mapped_column(JSON)
    flags: Mapped[list | None] = mapped_column(JSON)
    usage: Mapped[dict | None] = mapped_column(JSON)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    reserved_usd: Mapped[Decimal | None] = mapped_column(DecimalText)
    cost_usd: Mapped[Decimal | None] = mapped_column(DecimalText)
    data_cutoff: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reused_from: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(300))


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
    # M10 (migration 0006): the owner's own structured decision, and the current thesis version number.
    decision: Mapped[str | None] = mapped_column(String(12))  # WATCH | BUY | ADD | HOLD | TRIM | SELL | AVOID
    conviction: Mapped[int | None] = mapped_column(Integer)  # 1 (low) .. 5 (high)
    horizon: Mapped[str | None] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    instrument: Mapped[Instrument] = relationship(lazy="joined")
    tags: Mapped[list[JournalTag]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", lazy="selectin", order_by="JournalTag.tag"
    )


class JournalVersion(Base):
    """An immutable thesis version with the evidence observed when it was written. Never updated after insert."""

    __tablename__ = "journal_versions"
    __table_args__ = (UniqueConstraint("entry_id", "version", name="uq_journal_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[dict] = mapped_column(JSON, nullable=False)  # title, thesis, risks, invalidation, decision, ...
    evidence: Mapped[dict | None] = mapped_column(JSON)  # price, fundamentals, filings as observed at created_at


class JournalReview(Base):
    """A completed review of an entry: the outcome, notes and the evidence at review time. Never updated."""

    __tablename__ = "journal_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id", ondelete="CASCADE"), index=True)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # intact | weakened | invalidated | closed
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False)  # the thesis version that was reviewed
    scheduled_for: Mapped[date | None] = mapped_column(Date)  # the review date that was due
    next_review_date: Mapped[date | None] = mapped_column(Date)
    evidence: Mapped[dict | None] = mapped_column(JSON)


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


class ResearchCheck(Base):
    """When a company dataset was last checked, separately from how recent the reported facts are."""

    __tablename__ = "research_checks"
    __table_args__ = (UniqueConstraint("instrument_id", "dataset", name="uq_research_check"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False)
    dataset: Mapped[str] = mapped_column(String(32), nullable=False)  # sec_submissions | sec_companyfacts
    source_id: Mapped[str | None] = mapped_column(String(32))  # e.g. the CIK
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(200))
    latest_filing_date: Mapped[date | None] = mapped_column(Date)
    latest_accession: Mapped[str | None] = mapped_column(String(32))


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

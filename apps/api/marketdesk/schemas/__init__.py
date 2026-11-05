"""Pydantic API schemas. Decimals serialize as plain strings (never floats)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _fmt_decimal(d: Decimal) -> str:
    try:
        q = d.quantize(Decimal("1e-10"))
    except InvalidOperation:
        q = d
    s = format(q.normalize(), "f")
    return "0" if s in ("-0", "") else s


Dec = Annotated[Decimal, PlainSerializer(_fmt_decimal, return_type=str, when_used="json")]
DataStatus = Literal["sample", "available", "cached", "stale", "missing", "unsupported", "unavailable"]


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------------------- market
class DataMetaOut(Model):
    source: str
    status: DataStatus
    fetched_at: datetime | None = None
    market_time: datetime | None = None
    currency: str | None = None
    timezone: str | None = None
    message: str | None = None
    error_kind: str | None = None


class InstrumentOut(Model):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    timezone: str | None = None
    kind: str | None = None
    exchange_code: str | None = None
    mic: str | None = None
    country: str | None = None
    identity_verified: bool = False


class QuoteOut(Model):
    last_price: Dec
    previous_close: Dec | None = None
    change: Dec | None = None
    change_percent: Dec | None = None
    day_high: Dec | None = None
    day_low: Dec | None = None
    volume: int | None = None
    volume_note: str | None = None
    session_date: date | None = None
    market_time: datetime


class SparkPoint(Model):
    date: date
    close: Dec


class SnapshotOut(Model):
    symbol: str
    instrument: InstrumentOut
    quote: QuoteOut | None = None
    sparkline: list[SparkPoint] = []
    meta: DataMetaOut


class SearchResultOut(Model):
    results: list[InstrumentOut]
    meta: DataMetaOut


class BarOut(Model):
    time: date
    open: Dec | None = None
    high: Dec | None = None
    low: Dec | None = None
    close: Dec
    volume: int | None = None


class HistoryOut(Model):
    symbol: str
    range: str
    adjustment: str | None = None
    bars: list[BarOut] = []
    meta: DataMetaOut
    supported_ranges: list[str]


class MarketSessionOut(Model):
    market: str
    name: str
    timezone: str
    calendar: str | None = None
    source: str
    as_of: datetime
    state: Literal["open", "closed", "unknown"]
    reason: str
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    next_open: datetime | None = None


class CompareInstrumentOut(Model):
    symbol: str
    name: str | None = None
    currency: str | None = None
    exchange: str | None = None
    country: str | None = None
    adjustment: str | None = None
    bars: int
    excluded_dates: int | None = None
    meta: DataMetaOut


class CompareOut(Model):
    range: str
    method: str
    base_date: date | None = None
    dates: list[date]
    series: dict[str, list[Dec]]
    instruments: list[CompareInstrumentOut]
    complete: bool
    currencies_differ: bool


class FundamentalsValues(Model):
    market_cap: Dec | None = None
    pe_ratio: Dec | None = None
    dividend_yield_percent: Dec | None = None
    fifty_two_week_high: Dec | None = None
    fifty_two_week_low: Dec | None = None
    price_to_book: Dec | None = None
    sector: str | None = None
    industry: str | None = None
    last_fiscal_year_end: date | None = None
    most_recent_quarter: date | None = None
    notes: list[str] = []


class FundamentalsOut(Model):
    symbol: str
    currency: str | None = None
    values: FundamentalsValues | None = None
    meta: DataMetaOut


class CorporateActionOut(Model):
    date: date
    kind: str
    value: Dec
    description: str


class ActionsOut(Model):
    symbol: str
    actions: list[CorporateActionOut] = []
    meta: DataMetaOut


# ----------------------------------------------------------------------------- watchlists
class WatchlistIn(Model):
    name: str = Field(min_length=1, max_length=60)


class WatchlistPatch(Model):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    sort_key: Literal["manual", "symbol", "name", "change_percent", "last_price", "volume"] | None = None
    sort_dir: Literal["asc", "desc"] | None = None


class WatchlistItemOut(Model):
    symbol: str
    instrument: InstrumentOut
    position: int
    added_at: datetime


class WatchlistOut(Model):
    id: int
    name: str
    position: int
    sort_key: str
    sort_dir: str
    item_count: int
    items: list[WatchlistItemOut] = []
    created_at: datetime
    updated_at: datetime


class AddSymbolIn(Model):
    symbol: str = Field(min_length=1, max_length=32)


class ReorderIn(Model):
    symbols: list[str] = Field(max_length=200)


class MembershipOut(Model):
    symbol: str
    watchlist_ids: list[int]


# ----------------------------------------------------------------------------- portfolio
TxnTypeLit = Literal["DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "SPLIT", "FX"]
AccountCcy = Literal["INR", "USD"]


class TransactionIn(Model):
    type: TxnTypeLit
    effective_date: date
    symbol: str | None = Field(default=None, max_length=32)
    quantity: Decimal | None = None
    price: Decimal | None = None
    fees: Decimal = Decimal("0")
    amount: Decimal | None = None
    split_from: Decimal | None = None
    split_to: Decimal | None = None
    split_confirmed: bool = False
    currency: AccountCcy = "INR"  # the account; for FX, the account paying
    counter_currency: AccountCcy | None = None  # FX only: the account receiving
    counter_amount: Decimal | None = None  # FX only: amount received, in counter_currency
    fx_rate: Decimal | None = None  # FX only: quoted USD/INR rate, INR per 1 USD, whichever way money moved (optional)
    fx_source: str | None = Field(default=None, max_length=80)  # FX only: bank/broker/provider of the rate
    fx_time: datetime | None = None  # FX only: when the rate applied
    notes: str | None = Field(default=None, max_length=500)


class TransactionOut(Model):
    id: int
    type: TxnTypeLit
    effective_date: date
    symbol: str | None = None
    instrument_name: str | None = None
    quantity: Dec | None = None
    price: Dec | None = None
    fees: Dec
    amount: Dec | None = None
    split_from: Dec | None = None
    split_to: Dec | None = None
    currency: str
    counter_currency: str | None = None
    counter_amount: Dec | None = None
    fx_rate: Dec | None = None
    effective_rate: Dec | None = None
    fx_source: str | None = None
    fx_time: datetime | None = None
    notes: str | None = None
    source: str
    cash_effect: Dec
    cash_after: Dec | None = None
    realized_pnl: Dec | None = None
    created_at: datetime
    created_via: str
    updated_at: datetime


class TransactionPage(Model):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class HoldingOut(Model):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    quantity: Dec
    average_cost: Dec | None = None
    cost_basis: Dec
    last_price: Dec | None = None
    market_value: Dec | None = None
    unrealized_pnl: Dec | None = None
    unrealized_pct: Dec | None = None
    realized_pnl: Dec
    dividends: Dec
    weight_pct: Dec | None = None
    mark_status: str
    mark_time: datetime | None = None
    mark_message: str | None = None


class PortfolioSummaryOut(Model):
    currency: AccountCcy = "INR"
    has_transactions: bool
    fx_in: Dec = Decimal("0")
    fx_out: Dec = Decimal("0")
    cash: Dec
    holdings_value: Dec
    total_equity: Dec | None = None
    partial_equity: Dec
    unrealized_pnl: Dec | None = None
    realized_pnl: Dec
    dividends: Dec
    fees: Dec
    total_profit_before_dividends: Dec | None = None
    deposits: Dec
    withdrawals: Dec
    net_contributions: Dec
    complete: bool
    missing_marks: list[str]
    stale_marks: list[str]
    cash_weight_pct: Dec | None = None
    holdings: list[HoldingOut]
    accounting_note: str
    valuation_source: str


class FxRateOut(Model):
    pair: str
    rate: Dec | None = None
    status: str
    market_time: datetime | None = None
    fetched_at: datetime | None = None
    source: str | None = None
    symbol: str | None = None
    message: str | None = None


class AccountValueOut(Model):
    currency: AccountCcy
    cash: Dec
    holdings_value: Dec
    total_equity: Dec | None = None
    partial_equity: Dec
    complete: bool
    stale_marks: list[str]
    value_in_base: Dec | None = None
    partial_in_base: Dec | None = None
    rate: FxRateOut


class PortfolioOverviewOut(Model):
    base_currency: AccountCcy
    accounts: list[AccountValueOut]
    complete: bool
    total_in_base: Dec | None = None
    partial_in_base: Dec
    incomplete_reasons: list[str]
    stale_rates: list[str]
    note: str


class ImportRowOut(Model):
    row: int
    status: Literal["ok", "error", "duplicate"]
    values: dict[str, str | None]
    messages: list[str] = []


class ImportPreviewOut(Model):
    token: str | None = None
    filename: str | None = None
    total_rows: int
    ok_rows: int
    error_rows: int
    duplicate_rows: int
    can_import: bool
    blocking_reason: str | None = None
    ledger_error: dict | None = None
    header_errors: list[str] = []
    rows: list[ImportRowOut]


class ImportCommitOut(Model):
    imported: int
    skipped_duplicates: int
    batch_id: int


# ----------------------------------------------------------------------------- alerts
RuleName = Literal["PRICE", "CROSS", "VOLUME", "VOLATILITY", "FILING", "EARNINGS"]
HHMM = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]


class AlertParams(Model):
    lookback: int | None = Field(default=None, ge=5, le=60)
    forms: list[Literal["10-K", "10-Q", "8-K", "20-F", "6-K", "DEF 14A"]] | None = Field(default=None, max_length=6)
    days_before: int | None = Field(default=None, ge=0, le=30)  # EARNINGS reminders


class AlertIn(Model):
    symbol: str = Field(min_length=1, max_length=32)
    rule: RuleName = "PRICE"
    direction: Literal["ABOVE", "BELOW"] = "ABOVE"
    # PRICE/CROSS: the price level. VOLUME/VOLATILITY: the multiple. FILING: not used.
    target_price: Decimal | None = Field(default=None, gt=0)
    params: AlertParams | None = None
    cooldown_minutes: int | None = Field(default=None, ge=5, le=7 * 24 * 60)
    quiet_start: HHMM | None = None
    quiet_end: HHMM | None = None
    note: str | None = Field(default=None, max_length=280)


class AlertPatch(Model):
    direction: Literal["ABOVE", "BELOW"] | None = None
    target_price: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=280)
    active: bool | None = None
    cooldown_minutes: int | None = Field(default=None, ge=5, le=7 * 24 * 60)
    quiet_start: HHMM | None = None
    quiet_end: HHMM | None = None


class DeliveryOut(Model):
    channel: str
    status: Literal["delivered", "held", "failed"]
    attempts: int
    last_error: str | None = None


class AlertEventOut(Model):
    id: int
    alert_id: int
    symbol: str
    arm_seq: int
    rule: str
    direction: str
    target_price: Dec | None = None
    observed_price: Dec | None = None
    observed_market_time: datetime | None = None
    provider: str
    triggered_at: datetime
    read_at: datetime | None = None
    explanation: str | None = None
    link: str | None = None
    deliver_after: datetime | None = None
    deliveries: list[DeliveryOut] = []


class AlertOut(Model):
    id: int
    symbol: str
    instrument: InstrumentOut
    rule: str
    description: str
    direction: str
    target_price: Dec
    params: dict = {}
    cooldown_minutes: int | None = None
    rearm_at: datetime | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    last_skip_reason: str | None = None
    note: str | None = None
    active: bool
    arm_seq: int
    armed_at: datetime
    last_evaluated_at: datetime | None = None
    last_observed_price: Dec | None = None
    last_observed_market_time: datetime | None = None
    created_at: datetime
    events: list[AlertEventOut] = []


class StoredBriefingOut(Model):
    id: int
    kind: Literal["morning", "close"]
    market: str
    market_name: str
    session_date: date
    provider: str
    created_at: datetime
    read_at: datetime | None = None
    title: str
    items: list[BriefingItem]
    method: str
    data_status: str | None = None
    reference_session: str | None = None


class InboxItemOut(Model):
    type: Literal["alert", "briefing"]
    id: int
    at: datetime
    read_at: datetime | None = None
    market: str | None = None
    title: str
    alert: AlertEventOut | None = None
    briefing: StoredBriefingOut | None = None


class InboxCountsOut(Model):
    alerts: int
    briefings: int
    total: int
    held: int


class InboxReadIn(Model):
    type: Literal["alert", "briefing"] | None = None
    id: int | None = None


class WorkerStatusOut(Model):
    running: bool
    stale: bool
    provider: str | None = None
    started_at: datetime | None = None
    last_cycle_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    cycles: int = 0
    poll_seconds: int
    last_summary: dict | None = None
    message: str


# ----------------------------------------------------------------------------- journal
class JournalIn(Model):
    symbol: str = Field(min_length=1, max_length=32)
    entry_date: date
    title: str = Field(min_length=1, max_length=160)
    thesis: str = Field(default="", max_length=10_000)
    risks: str = Field(default="", max_length=10_000)
    invalidation: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    review_date: date | None = None
    decision: Literal["WATCH", "BUY", "ADD", "HOLD", "TRIM", "SELL", "AVOID"] | None = None
    conviction: int | None = Field(default=None, ge=1, le=5)
    horizon: str | None = Field(default=None, max_length=40)
    change_note: str | None = Field(default=None, max_length=500)  # required when an edit changes the thesis


class JournalOut(Model):
    id: int
    symbol: str
    instrument: InstrumentOut
    entry_date: date
    title: str
    thesis: str
    risks: str
    invalidation: str
    decision: str | None = None
    conviction: int | None = None
    horizon: str | None = None
    version: int = 1
    tags: list[str]
    review_date: date | None = None
    review_due: bool
    created_at: datetime
    updated_at: datetime


class JournalVersionOut(Model):
    version: int
    created_at: datetime
    change_note: str | None = None
    content: dict
    evidence: dict | None = None


class JournalReviewIn(Model):
    outcome: Literal["intact", "weakened", "invalidated", "closed"]
    notes: str = Field(default="", max_length=10_000)
    next_review_date: date | None = None


class JournalReviewOut(Model):
    id: int
    reviewed_at: datetime
    outcome: str
    notes: str
    version: int
    scheduled_for: date | None = None
    next_review_date: date | None = None
    evidence: dict | None = None


class JournalDetailOut(JournalOut):
    versions: list[JournalVersionOut]
    reviews: list[JournalReviewOut]


class JournalCompareOut(Model):
    version: int
    version_created_at: datetime
    then: dict
    now: dict
    price_change_pct: Dec | None = None
    price_note: str
    splits_since: list[dict]
    filings_since: list[dict]
    days_elapsed: int


class JournalPage(Model):
    items: list[JournalOut]
    total: int
    tags: list[str]
    symbols: list[str]


# ----------------------------------------------------------------------------- system
class PrefsOut(Model):
    theme: Literal["dark", "light", "system"] = "dark"
    density: Literal["comfortable", "compact"] = "comfortable"
    default_watchlist_id: int | None = None
    chart_symbol: str | None = None
    display_timezone: str = "Asia/Kolkata"
    quote_refresh_seconds: Literal[0, 30, 60, 120, 300] = 60


class PrefsPatch(Model):
    theme: Literal["dark", "light", "system"] | None = None
    density: Literal["comfortable", "compact"] | None = None
    default_watchlist_id: int | None = None
    chart_symbol: str | None = Field(default=None, max_length=32)
    display_timezone: str | None = Field(default=None, max_length=64)
    quote_refresh_seconds: Literal[0, 30, 60, 120, 300] | None = None


class WorkspaceIn(Model):
    name: str = Field(min_length=1, max_length=40)
    start: str = Field(default="/", max_length=32)
    density: Literal["comfortable", "compact"] = "comfortable"
    default_watchlist_id: int | None = None  # None: keep the current default
    chart_symbol: str | None = Field(default=None, max_length=32)  # None: keep the current chart symbol


class WorkspaceOut(WorkspaceIn):
    id: str


class WorkspacesOut(Model):
    active: str | None
    items: list[WorkspaceOut]
    start_pages: list[dict[str, str]]


class WorkspaceApplied(Model):
    workspace: WorkspaceOut
    prefs: PrefsOut
    notes: list[str]


class SessionOut(Model):
    authenticated: bool
    mode: Literal["owner", "dev_bypass"]
    username: str | None = None
    csrf_token: str | None = None
    read_only: bool


class LoginIn(Model):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class FixtureStateOut(Model):
    enabled: bool
    cursor_index: int = 0
    cursor_date: date | None = None
    base_date: date | None = None
    sessions: list[date] = []
    fault: bool = False


class StorageOut(Model):
    path: str
    persistent: bool
    warning: bool
    message: str
    database_created_at: datetime | None = None
    round_trip_ms: float | None = None


class SchemaOut(Model):
    current: str | None = None
    head: str | None = None
    up_to_date: bool


class StatusOut(Model):
    version: str
    environment: str
    provider: str
    sample_data: bool
    dataset_date: date | None = None
    dataset_disclaimer: str | None = None
    read_only: bool
    auth_mode: str
    market_status: str
    provider_health: dict
    worker: WorkerStatusOut
    storage: StorageOut
    schema_: SchemaOut = Field(alias="schema", serialization_alias="schema")
    research: dict = {}
    benchmarks: list[str]
    attribution: list[dict]


class BriefingItem(Model):
    kind: Literal["move", "threshold", "alert", "review", "coverage", "info", "session", "volume"]
    tone: Literal["positive", "negative", "neutral", "info", "warning"]
    symbol: str | None = None
    text: str
    detail: str | None = None


class BriefingOut(Model):
    generated_at: datetime
    watchlist_id: int | None = None
    watchlist_name: str | None = None
    items: list[BriefingItem]
    method: str
    data_status: DataStatus | None = None

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
TxnTypeLit = Literal["DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "SPLIT"]


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
    currency: Literal["INR"] = "INR"
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
    currency: Literal["INR"] = "INR"
    has_transactions: bool
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
class AlertIn(Model):
    symbol: str = Field(min_length=1, max_length=32)
    direction: Literal["ABOVE", "BELOW"]
    target_price: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=280)


class AlertPatch(Model):
    direction: Literal["ABOVE", "BELOW"] | None = None
    target_price: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=280)
    active: bool | None = None


class AlertEventOut(Model):
    id: int
    alert_id: int
    symbol: str
    arm_seq: int
    direction: str
    target_price: Dec
    observed_price: Dec
    observed_market_time: datetime | None = None
    provider: str
    triggered_at: datetime
    read_at: datetime | None = None


class AlertOut(Model):
    id: int
    symbol: str
    instrument: InstrumentOut
    direction: str
    target_price: Dec
    note: str | None = None
    active: bool
    arm_seq: int
    armed_at: datetime
    last_evaluated_at: datetime | None = None
    last_observed_price: Dec | None = None
    last_observed_market_time: datetime | None = None
    created_at: datetime
    events: list[AlertEventOut] = []


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


class JournalOut(Model):
    id: int
    symbol: str
    instrument: InstrumentOut
    entry_date: date
    title: str
    thesis: str
    risks: str
    invalidation: str
    tags: list[str]
    review_date: date | None = None
    review_due: bool
    created_at: datetime
    updated_at: datetime


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


class PrefsPatch(Model):
    theme: Literal["dark", "light", "system"] | None = None
    density: Literal["comfortable", "compact"] | None = None
    default_watchlist_id: int | None = None
    chart_symbol: str | None = Field(default=None, max_length=32)
    display_timezone: str | None = Field(default=None, max_length=64)


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
    benchmarks: list[str]
    attribution: list[dict]


class BriefingItem(Model):
    kind: Literal["move", "threshold", "alert", "review", "coverage", "info"]
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

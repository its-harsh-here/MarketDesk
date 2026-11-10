"""Market data provider interface and normalized value types.

Providers fetch and normalize. They never invent values: anything the upstream does
not supply is ``None`` and rendered by the UI as an explained em dash.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

ErrorKind = Literal["missing", "unsupported", "upstream_unavailable", "rate_limited", "malformed", "timeout"]
HistoryRange = Literal["1M", "3M", "6M", "1Y", "5Y"]
HISTORY_RANGES: tuple[HistoryRange, ...] = ("1M", "3M", "6M", "1Y", "5Y")


class ProviderError(Exception):
    """Structured availability error raised by providers."""

    def __init__(self, kind: ErrorKind, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message}


@dataclass(frozen=True)
class InstrumentRef:
    symbol: str
    name: str | None
    exchange: str | None
    currency: str | None
    timezone: str | None
    kind: str | None  # EQUITY | INDEX | ETF | MUTUALFUND | ...
    # Canonical listing identity, derived from the provider's own exchange code (never from the ticker text alone).
    exchange_code: str | None = None  # provider's raw venue code, e.g. Yahoo "NSI", "NMS", "NYQ"
    mic: str | None = None  # ISO 10383 market identifier of the listing venue, e.g. XNSE, XNAS
    country: str | None = None  # ISO 3166-1 alpha-2 of the venue, e.g. IN, US

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DailyBar:
    session_date: date  # exchange-local trading date, not a UTC instant
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None


@dataclass(frozen=True)
class QuoteSnapshot:
    """Latest observation plus recent daily closes (same adjustment basis as previous close)."""

    instrument: InstrumentRef
    last_price: Decimal
    previous_close: Decimal | None
    market_time: datetime  # UTC instant of the quotation as reported by the provider
    session_date: date | None
    day_high: Decimal | None
    day_low: Decimal | None
    volume: int | None
    volume_note: str | None
    recent_bars: list[DailyBar] = field(default_factory=list)

    @property
    def change(self) -> Decimal | None:
        if self.previous_close is None:
            return None
        return self.last_price - self.previous_close

    @property
    def change_percent(self) -> Decimal | None:
        if self.previous_close is None or self.previous_close == 0:
            return None
        return (self.last_price - self.previous_close) / self.previous_close * Decimal(100)


@dataclass(frozen=True)
class PriceHistory:
    instrument: InstrumentRef
    range: HistoryRange
    bars: list[DailyBar]
    adjustment: str  # human-readable adjustment basis


@dataclass(frozen=True)
class Fundamentals:
    instrument: InstrumentRef
    market_cap: Decimal | None  # absolute, in `currency`
    pe_ratio: Decimal | None  # ratio (x), trailing
    dividend_yield_percent: Decimal | None  # percent points, e.g. 1.25 means 1.25%
    fifty_two_week_high: Decimal | None
    fifty_two_week_low: Decimal | None
    price_to_book: Decimal | None  # ratio (x)
    sector: str | None
    industry: str | None
    last_fiscal_year_end: date | None
    most_recent_quarter: date | None
    notes: list[str] = field(default_factory=list)
    summary: str | None = None  # the provider's business description, as supplied (not verified)


@dataclass(frozen=True)
class AnnualPeriod:
    """One fiscal year from the provider's annual statements. Values are in the statement currency (often not
    reported by the endpoint), so only ratios between values of the same statement set are used downstream."""

    period_end: date
    revenue: Decimal | None
    net_income: Decimal | None
    total_debt: Decimal | None
    total_equity: Decimal | None
    operating_cash_flow: Decimal | None = None
    capex: Decimal | None = None  # capital expenditure as a positive amount spent
    cash: Decimal | None = None  # cash and equivalents (with short-term investments where reported together)


@dataclass(frozen=True)
class AnnualStatements:
    instrument: InstrumentRef
    periods: list[AnnualPeriod]  # newest first
    source: str  # e.g. "Yahoo annual statements"
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CorporateAction:
    action_date: date
    kind: Literal["DIVIDEND", "SPLIT"]
    value: Decimal  # dividend per share, or split ratio (new shares per old share)
    description: str


@dataclass(frozen=True)
class NewsItem:
    """A provider headline: title, publisher and link only (no article body is fetched or stored)."""

    title: str
    publisher: str | None
    url: str | None  # http(s) only; None for the fictitious sample headlines
    published_at: datetime | None  # UTC
    kind: str = "news"  # "news", "press_release", "video" … as the provider labels it


class MarketDataProvider(Protocol):
    name: str
    is_sample: bool

    def search(self, query: str, limit: int) -> list[InstrumentRef]: ...

    def quote(self, symbol: str) -> QuoteSnapshot: ...

    def history(self, symbol: str, range_: HistoryRange) -> PriceHistory: ...

    def fundamentals(self, symbol: str) -> Fundamentals: ...

    def corporate_actions(self, symbol: str) -> list[CorporateAction]: ...

    def annual_statements(self, symbol: str) -> AnnualStatements: ...

    def news(self, symbol: str) -> list[NewsItem]: ...

    def validate_symbol(self, symbol: str) -> str: ...


def validate_bars(bars: list[DailyBar]) -> list[DailyBar]:
    """Return bars sorted ascending with duplicate dates removed (last wins) and invalid rows dropped."""
    by_date: dict[date, DailyBar] = {}
    for bar in bars:
        if bar.close is None or not bar.close.is_finite() or bar.close <= 0:
            continue
        o, h, low = bar.open, bar.high, bar.low
        if None not in (o, h, low):
            assert o is not None and h is not None and low is not None
            if not (low <= min(o, bar.close) and h >= max(o, bar.close) and low <= h):
                # Inconsistent OHLC: keep the close (line chart) but drop the candle body.
                o = h = low = None
        by_date[bar.session_date] = DailyBar(bar.session_date, o, h, low, bar.close, bar.volume)
    return [by_date[d] for d in sorted(by_date)]

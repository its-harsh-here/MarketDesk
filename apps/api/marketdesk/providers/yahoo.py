"""YahooProvider: live data through the unofficial yfinance library.

yfinance is not an official Yahoo API. Review its documentation and Yahoo's terms before
any public redistribution. All calls here are blocking; the market service runs them in a
bounded thread pool with timeouts, retries and a circuit breaker.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from marketdesk.providers.base import (
    AnnualPeriod,
    AnnualStatements,
    CorporateAction,
    DailyBar,
    Fundamentals,
    HistoryRange,
    InstrumentRef,
    PriceHistory,
    ProviderError,
    QuoteSnapshot,
    validate_bars,
)
from marketdesk.providers.venues import security_type, venue_for

log = logging.getLogger("marketdesk.providers.yahoo")

_SYMBOL_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-&=]{0,23}$")
_PERIODS: dict[str, str] = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "1Y": "1y", "5Y": "5y"}
_SEARCH_TYPES = {"EQUITY", "ETF", "INDEX", "MUTUALFUND"}
ADJUSTMENT_NOTE = (
    "Yahoo daily bars via yfinance (auto_adjust=False): OHLC as reported by Yahoo, which is "
    "split-adjusted; dividends are not adjusted."
)


def _dec(value: Any, places: int | None = None) -> Decimal | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    d = Decimal(repr(f))
    if places is not None:
        d = d.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
    return d


def _int(value: Any) -> int | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return int(f)


def _to_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return None
        return datetime.fromtimestamp(float(value), UTC)
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(UTC)
    return None


def _epoch_date(value: Any) -> date | None:
    dt = _to_utc(value)
    return dt.date() if dt else None


def _session_date(idx: Any) -> date:
    if hasattr(idx, "to_pydatetime"):
        idx = idx.to_pydatetime()
    if isinstance(idx, datetime):
        return idx.date()  # index is exchange-local midnight; .date() keeps the trading date
    if isinstance(idx, date):
        return idx
    raise ValueError("Unrecognised bar index")


def normalize_bars(df: Any, places: int, is_index: bool) -> list[DailyBar]:
    """Convert a yfinance history DataFrame into validated ascending daily bars."""
    if df is None or getattr(df, "empty", True):
        return []
    for col in ("Close",):
        if col not in df.columns:
            raise ProviderError("malformed", "History response did not include closing prices.")
    bars: list[DailyBar] = []
    for idx, row in df.iterrows():
        close = _dec(row.get("Close"), places)
        if close is None:
            continue
        vol = _int(row.get("Volume")) if "Volume" in df.columns else None
        bars.append(
            DailyBar(
                session_date=_session_date(idx),
                open=_dec(row.get("Open"), places),
                high=_dec(row.get("High"), places),
                low=_dec(row.get("Low"), places),
                close=close,
                volume=None if is_index or not vol else vol,
            )
        )
    return validate_bars(bars)


def instrument_from_meta(symbol: str, meta: dict) -> InstrumentRef:
    code = meta.get("exchangeName")
    venue = venue_for(code, symbol)
    kind = security_type(meta.get("instrumentType"))
    return InstrumentRef(
        symbol=symbol,
        name=meta.get("longName") or meta.get("shortName"),
        exchange=meta.get("fullExchangeName") or code,
        currency=meta.get("currency"),
        timezone=meta.get("exchangeTimezoneName"),
        kind=kind,
        exchange_code=code,
        mic=venue.mic if venue and kind != "INDEX" else None,  # an index has no listing venue
        country=venue.country if venue else None,
    )


def quote_from_history(symbol: str, df: Any, meta: dict) -> QuoteSnapshot:
    """Build a quote whose last price and previous close come from one consistent series."""
    if not meta:
        raise ProviderError("malformed", "Quote metadata was empty.")
    places = int(meta.get("priceHint") or 2)
    ref = instrument_from_meta(symbol, meta)
    is_index = (ref.kind or "").upper() == "INDEX"
    bars = normalize_bars(df, places, is_index)
    last = _dec(meta.get("regularMarketPrice"), places)
    market_time = _to_utc(meta.get("regularMarketTime"))
    if last is None or market_time is None:
        raise ProviderError("missing", "Yahoo did not report a regular-market price and time for this symbol.")
    tz = ZoneInfo(ref.timezone) if ref.timezone else UTC
    session = market_time.astimezone(tz).date()
    prior = [b for b in bars if b.session_date < session]
    previous_close = prior[-1].close if prior else None
    volume = None if is_index else _int(meta.get("regularMarketVolume"))
    return QuoteSnapshot(
        instrument=ref,
        last_price=last,
        previous_close=previous_close,
        market_time=market_time,
        session_date=session,
        day_high=_dec(meta.get("regularMarketDayHigh"), places),
        day_low=_dec(meta.get("regularMarketDayLow"), places),
        volume=volume,
        volume_note=(
            "Index volume is not reported."
            if is_index
            else "Session volume as reported by Yahoo; incomplete if the session was still open."
        ),
        recent_bars=bars[-66:],
    )


def normalize_dividend_yield(info: dict) -> tuple[Decimal | None, str | None]:
    """Return dividend yield in percent points.

    Yahoo's ``dividendYield`` has been observed in percent points (e.g. 6.02 for 6.02%) in
    yfinance 1.7, while older responses used a fraction. Cross-check against
    ``dividendRate / price`` when possible instead of assuming a unit.
    """
    raw = _dec(info.get("dividendYield"))
    rate = _dec(info.get("dividendRate"))
    price = _dec(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"))
    if raw is None:
        return None, None
    if rate is not None and price and price > 0:
        implied = rate / price * 100
        as_percent = abs(raw - implied)
        as_fraction = abs(raw * 100 - implied)
        value = raw if as_percent <= as_fraction else raw * 100
        return value.quantize(Decimal("0.01")), "Yahoo dividendYield, unit cross-checked against dividendRate ÷ price."
    # Without a cross-check, treat values below 1 with suspicion rather than guessing.
    if raw < 1:
        return None, "Dividend yield unit could not be verified, so it is not shown."
    return raw.quantize(Decimal("0.01")), "Yahoo dividendYield (reported in percent points)."


class YahooProvider:
    name = "yahoo"
    is_sample = False

    def __init__(self, timeout: float = 10.0, cache_dir: Path | None = None):
        self.timeout = timeout
        self._cache_dir = cache_dir
        self._summary_blocked_until = 0.0
        self._module = None
        self._import_lock = threading.Lock()

    # yfinance (with pandas) takes about a second of CPU to import, which is ten seconds on a
    # 0.1-CPU free instance. It is imported on first use (or by warm() in the background) so the
    # web server can answer before it is loaded.
    @property
    def _yf(self):
        if self._module is None:
            with self._import_lock:
                if self._module is None:
                    import yfinance as yf

                    # Raise errors instead of logging and returning empty frames.
                    yf.config.debug.hide_exceptions = False
                    yf.config.network.retries = 0  # MarketDesk applies its own bounded retry policy
                    if self._cache_dir is not None:
                        self._cache_dir.mkdir(parents=True, exist_ok=True)
                        yf.set_tz_cache_location(str(self._cache_dir))
                    self._module = yf
        return self._module

    @_yf.setter
    def _yf(self, module) -> None:  # tests substitute a fake module
        self._module = module

    def warm(self) -> None:
        """Import yfinance now (called from a background thread after startup)."""
        _ = self._yf

    def cache_namespace(self) -> str:
        return "y3"  # bump when the shape or wording of cached provider payloads changes

    def validate_symbol(self, symbol: str) -> str:
        s = (symbol or "").strip().upper()
        if s.startswith("SX:"):
            raise ProviderError(
                "unsupported", "SX: symbols are fictitious sample instruments available only in fixture mode."
            )
        if not _SYMBOL_RE.match(s):
            raise ProviderError("unsupported", f"'{symbol}' is not a valid Yahoo symbol.")
        return s

    # -- error mapping -----------------------------------------------------------
    def _call(self, fn, what: str):
        from yfinance import exceptions as yfe

        try:
            return fn()
        except ProviderError:
            raise
        except yfe.YFRateLimitError as exc:
            raise ProviderError("rate_limited", "Yahoo rate-limited the request (HTTP 429).", retryable=True) from exc
        except yfe.YFInvalidPeriodError as exc:
            raise ProviderError("unsupported", "Yahoo does not support this range for the symbol.") from exc
        except yfe.YFTickerMissingError as exc:
            raise ProviderError("missing", f"Yahoo returned no {what} for this symbol (it may be delisted).") from exc
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
            log.warning("yahoo %s malformed: %s", what, type(exc).__name__)
            raise ProviderError("malformed", f"Yahoo returned a malformed {what} response.") from exc
        except TimeoutError as exc:
            raise ProviderError("timeout", f"Yahoo {what} request timed out.", retryable=True) from exc
        except Exception as exc:  # network errors from curl_cffi / requests
            name = type(exc).__name__
            status = _http_status(exc)
            log.warning("yahoo %s failed: %s %s", what, name, status or "")
            if status == 429:
                raise ProviderError(
                    "rate_limited", f"Yahoo rate-limited the {what} request (HTTP 429).", retryable=True
                ) from exc
            if status in (401, 403, 404) and _says_not_found(exc):
                raise ProviderError("missing", f"Yahoo has no {what} for this symbol (not found).") from exc
            if status in (401, 403):
                raise ProviderError(
                    "upstream_unavailable",
                    f"Yahoo returned HTTP {status} for this {what} request: the symbol may not exist, or Yahoo is "
                    "limiting requests from this server.",
                ) from exc
            if status == 404:
                raise ProviderError("missing", f"Yahoo has no {what} for this symbol (HTTP 404).") from exc
            kind = "timeout" if "Timeout" in name else "upstream_unavailable"
            detail = f"HTTP {status}" if status else name
            raise ProviderError(kind, f"Yahoo {what} request failed ({detail}).", retryable=True) from exc

    # -- interface ---------------------------------------------------------------
    def search(self, query: str, limit: int) -> list[InstrumentRef]:
        q = (query or "").strip()
        if not q:
            return []

        def run():
            s = self._yf.Search(
                q,
                max_results=limit,
                news_count=0,
                lists_count=0,
                include_cb=False,
                recommended=0,
                enable_fuzzy_query=False,
                timeout=self.timeout,
                raise_errors=True,
            )
            return s.quotes or []

        quotes = self._call(run, "search")
        out: list[InstrumentRef] = []
        for item in quotes:
            sym = item.get("symbol")
            qtype = (item.get("quoteType") or "").upper()
            if not sym or qtype not in _SEARCH_TYPES:
                continue
            code = item.get("exchange")
            venue = venue_for(code, str(sym))
            out.append(
                InstrumentRef(
                    symbol=str(sym).upper(),
                    name=item.get("longname") or item.get("shortname"),
                    exchange=item.get("exchDisp") or (venue.name if venue else code),
                    currency=None,  # Yahoo search does not report currency; resolved from the quote
                    timezone=venue.timezone if venue else None,
                    kind=security_type(qtype),
                    exchange_code=code,
                    mic=venue.mic if venue and qtype != "INDEX" else None,
                    country=venue.country if venue else None,
                )
            )
        return out[:limit]

    def quote(self, symbol: str) -> QuoteSnapshot:
        symbol = self.validate_symbol(symbol)

        def run():
            t = self._yf.Ticker(symbol)
            df = t.history(period="3mo", interval="1d", auto_adjust=False, actions=False, timeout=self.timeout)
            return quote_from_history(symbol, df, dict(t.history_metadata or {}))

        return self._call(run, "quote")

    def history(self, symbol: str, range_: HistoryRange) -> PriceHistory:
        symbol = self.validate_symbol(symbol)
        if range_ not in _PERIODS:
            raise ProviderError("unsupported", f"Range {range_} is not supported.")

        def run():
            t = self._yf.Ticker(symbol)
            df = t.history(
                period=_PERIODS[range_], interval="1d", auto_adjust=False, actions=False, timeout=self.timeout
            )
            meta = dict(t.history_metadata or {})
            ref = instrument_from_meta(symbol, meta)
            bars = normalize_bars(df, int(meta.get("priceHint") or 2), (ref.kind or "").upper() == "INDEX")
            if not bars:
                raise ProviderError("missing", "Yahoo returned no daily bars for this range.")
            return PriceHistory(instrument=ref, range=range_, bars=bars, adjustment=ADJUSTMENT_NOTE)

        return self._call(run, "history")

    def fundamentals(self, symbol: str) -> Fundamentals:
        """Company summary (quoteSummary) when Yahoo allows it; otherwise derived fields.

        Yahoo's company-summary endpoint needs a cookie+crumb and is often refused for cloud IPs.
        The fallback uses endpoints that keep working there: price history (52-week range,
        dividends), valuation measures (market cap, trailing P/E, P/B), statements (dates) and
        search (sector, industry). Each derived field is labelled in the notes.
        """
        symbol = self.validate_symbol(symbol)
        primary: ProviderError | None = None
        if time.monotonic() >= self._summary_blocked_until:

            def run():
                info = self._yf.Ticker(symbol).info or {}
                if len(info) < 5:
                    raise ProviderError("missing", "Yahoo returned an empty company summary.")
                return fundamentals_from_info(symbol, info)

            try:
                return self._call(run, "company summary")
            except ProviderError as err:
                if err.kind == "unsupported":
                    raise
                primary = err
                if err.kind in ("upstream_unavailable", "rate_limited"):
                    # Don't hammer an endpoint that refuses this server; retry it in an hour.
                    self._summary_blocked_until = time.monotonic() + 3600
        else:
            primary = ProviderError("upstream_unavailable", "Yahoo's company summary was recently refused.")
        return self._call(lambda: self._derived_fundamentals(symbol, primary), "fundamentals")

    def _derived_fundamentals(self, symbol: str, primary: ProviderError | None) -> Fundamentals:
        t = self._yf.Ticker(symbol)
        df = t.history(period="1y", interval="1d", auto_adjust=False, actions=True, timeout=self.timeout)
        meta = dict(t.history_metadata or {})
        ref = instrument_from_meta(symbol, meta)
        places = int(meta.get("priceHint") or 2)
        is_index = (ref.kind or "").upper() == "INDEX"
        bars = normalize_bars(df, places, is_index)
        if not bars:
            raise ProviderError("missing", "Yahoo returned no price history for this symbol.")
        # The symbol clearly exists here (we have its price history), so explain only the summary refusal.
        code = re.search(r"HTTP (\d{3})", primary.message) if primary else None
        reason = (
            f"Yahoo's company summary is not available to this server (HTTP {code.group(1)})."
            if code
            else "Yahoo's company summary is not available right now."
        )
        notes = [f"{reason} These figures are derived from Yahoo's price history, valuation and statement data."]
        last = _dec(meta.get("regularMarketPrice"), places) or bars[-1].close
        high = _dec(meta.get("fiftyTwoWeekHigh"), places) or max((b.high or b.close) for b in bars)
        low = _dec(meta.get("fiftyTwoWeekLow"), places) or min((b.low or b.close) for b in bars)

        dividend_yield = None
        if is_index:
            notes.append("Valuation figures are not applicable to an index.")
        else:
            cutoff = bars[-1].session_date - timedelta(days=365)
            total = Decimal(0)
            if df is not None and "Dividends" in getattr(df, "columns", []):
                for idx, row in df.iterrows():
                    d = _dec(row.get("Dividends"))
                    if d and d > 0 and _session_date(idx) > cutoff:
                        total += d
            if total > 0 and last:
                dividend_yield = (total / last * 100).quantize(Decimal("0.01"))
                notes.append("Dividend yield = dividends paid in the last 12 months ÷ last price.")
            else:
                notes.append("No dividends in the last 12 months of Yahoo's price history.")

        market_cap = pe = pb = None
        last_fy = mrq = None
        sector = industry = None
        if not is_index:
            try:
                vm = t.get_valuation_measures(freq="quarterly")
                if vm is not None and not vm.empty:
                    col = "Current" if "Current" in vm.columns else vm.columns[0]

                    def cell(label: str, digits: int) -> Decimal | None:
                        return _dec(vm.at[label, col], digits) if label in vm.index else None

                    market_cap, pe, pb = cell("Market Cap", 0), cell("Trailing P/E", 2), cell("Price/Book", 2)
                    notes.append("Market cap, trailing P/E and P/B come from Yahoo valuation measures (latest).")
            except Exception as exc:  # optional enrichment
                notes.append(f"Valuation measures unavailable ({_describe(exc)}).")
            for freq in ("quarterly", "yearly"):
                try:
                    stmt = t.get_income_stmt(freq=freq)
                    dates = [_session_date(c) for c in getattr(stmt, "columns", [])]
                    if dates:
                        if freq == "quarterly":
                            mrq = max(dates)
                        else:
                            last_fy = max(dates)
                except Exception as exc:
                    notes.append(f"{freq.title()} statement dates unavailable ({_describe(exc)}).")
            try:
                found = (
                    self._yf.Search(
                        symbol,
                        max_results=5,
                        news_count=0,
                        lists_count=0,
                        include_cb=False,
                        recommended=0,
                        timeout=self.timeout,
                        raise_errors=True,
                    ).quotes
                    or []
                )
                match = next((q for q in found if str(q.get("symbol", "")).upper() == symbol), None)
                if match:
                    sector, industry = (
                        match.get("sectorDisp") or match.get("sector"),
                        match.get("industryDisp") or match.get("industry"),
                    )
            except Exception as exc:
                notes.append(f"Sector and industry unavailable ({_describe(exc)}).")
        return Fundamentals(
            instrument=ref,
            market_cap=market_cap,
            pe_ratio=pe,
            dividend_yield_percent=dividend_yield,
            fifty_two_week_high=high,
            fifty_two_week_low=low,
            price_to_book=pb,
            sector=sector,
            industry=industry,
            last_fiscal_year_end=last_fy,
            most_recent_quarter=mrq,
            notes=notes,
        )

    def annual_statements(self, symbol: str) -> AnnualStatements:
        """Up to four fiscal years of revenue, net income, total debt and shareholders' equity (Yahoo's
        fundamentals timeseries, which works for cloud servers). The statement currency is not reported by this
        endpoint, so callers use only ratios between these values."""
        symbol = self.validate_symbol(symbol)

        def run():
            t = self._yf.Ticker(symbol)
            income = t.get_income_stmt(freq="yearly")
            balance = t.get_balance_sheet(freq="yearly")
            return statements_from_frames(symbol, income, balance)

        return self._call(run, "annual statements")

    def corporate_actions(self, symbol: str) -> list[CorporateAction]:
        symbol = self.validate_symbol(symbol)

        def run():
            df = self._yf.Ticker(symbol).actions
            out: list[CorporateAction] = []
            if df is None or df.empty:
                return out
            for idx, row in df.iterrows():
                d = _session_date(idx)
                div = _dec(row.get("Dividends"))
                split = _dec(row.get("Stock Splits"))
                if div and div > 0:
                    out.append(CorporateAction(d, "DIVIDEND", div, f"Dividend of {div} per share (Yahoo)"))
                if split and split > 0:
                    out.append(CorporateAction(d, "SPLIT", split, f"Split ratio {split} new shares per share (Yahoo)"))
            return sorted(out, key=lambda a: a.action_date, reverse=True)

        return self._call(run, "corporate actions")


def _http_status(exc: BaseException) -> int | None:
    """HTTP status from requests/curl_cffi HTTPError-style exceptions, if present."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) or getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _says_not_found(exc: BaseException) -> bool:
    try:
        text = (getattr(getattr(exc, "response", None), "text", "") or "").lower()
    except Exception:
        return False
    return "not found" in text or "no data found" in text


def _describe(exc: BaseException) -> str:
    status = _http_status(exc)
    return f"HTTP {status}" if status else type(exc).__name__


def _frame_row(df: Any, keys: tuple[str, ...]) -> dict[date, Decimal | None]:
    """{period_end: value} for the first row key present in a yfinance statement frame (index = line items)."""
    if df is None or getattr(df, "empty", True):
        return {}
    for key in keys:
        if key in df.index:
            row = df.loc[key]
            out: dict[date, Decimal | None] = {}
            for col in df.columns:
                try:
                    out[_session_date(col)] = _dec(row[col])
                except ValueError:
                    continue
            return out
    return {}


def statements_from_frames(symbol: str, income: Any, balance: Any) -> AnnualStatements:
    revenue = _frame_row(income, ("TotalRevenue", "OperatingRevenue", "Total Revenue"))
    net = _frame_row(income, ("NetIncome", "NetIncomeCommonStockholders", "Net Income"))
    debt = _frame_row(balance, ("TotalDebt", "Total Debt"))
    equity = _frame_row(balance, ("StockholdersEquity", "CommonStockEquity", "Stockholders Equity"))
    ends = sorted(set(revenue) | set(net) | set(debt) | set(equity), reverse=True)[:4]
    if not ends:
        raise ProviderError("missing", "Yahoo returned no annual statements for this symbol.")
    periods = [AnnualPeriod(e, revenue.get(e), net.get(e), debt.get(e), equity.get(e)) for e in ends]
    notes = ["Total debt and shareholders' equity are Yahoo's balance-sheet lines at each fiscal year end."]
    if not debt:
        notes.append("Yahoo reports no total-debt line for this company.")
    ref = InstrumentRef(symbol, None, None, None, None, None)
    return AnnualStatements(instrument=ref, periods=periods, source="Yahoo annual statements", notes=notes)


def fundamentals_from_info(symbol: str, info: dict) -> Fundamentals:
    notes: list[str] = []
    ref = InstrumentRef(
        symbol=symbol,
        name=info.get("longName") or info.get("shortName"),
        exchange=info.get("fullExchangeName") or info.get("exchange"),
        currency=info.get("currency"),
        timezone=info.get("exchangeTimezoneName"),
        kind=info.get("quoteType"),
    )
    dy, dy_note = normalize_dividend_yield(info)
    if dy_note:
        notes.append(dy_note)
    fin_ccy = info.get("financialCurrency")
    if fin_ccy and info.get("currency") and fin_ccy != info.get("currency"):
        notes.append(f"Financial statements are reported in {fin_ccy}; prices in {info.get('currency')}.")
    pe = _dec(info.get("trailingPE"), 2)
    if pe is None:
        notes.append("Trailing P/E not reported (may be negative earnings or missing coverage).")
    return Fundamentals(
        instrument=ref,
        market_cap=_dec(info.get("marketCap"), 0),
        pe_ratio=pe,
        dividend_yield_percent=dy,
        fifty_two_week_high=_dec(info.get("fiftyTwoWeekHigh"), 2),
        fifty_two_week_low=_dec(info.get("fiftyTwoWeekLow"), 2),
        price_to_book=_dec(info.get("priceToBook"), 2),
        sector=info.get("sector"),
        industry=info.get("industry"),
        last_fiscal_year_end=_epoch_date(info.get("lastFiscalYearEnd")),
        most_recent_quarter=_epoch_date(info.get("mostRecentQuarter")),
        notes=notes,
    )


__all__ = [
    "YahooProvider",
    "quote_from_history",
    "fundamentals_from_info",
    "normalize_dividend_yield",
    "statements_from_frames",
]

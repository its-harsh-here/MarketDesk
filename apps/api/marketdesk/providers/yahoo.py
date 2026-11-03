"""YahooProvider: live data through the unofficial yfinance library.

yfinance is not an official Yahoo API. Review its documentation and Yahoo's terms before
any public redistribution. All calls here are blocking; the market service runs them in a
bounded thread pool with timeouts, retries and a circuit breaker.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from marketdesk.providers.base import (
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
    return InstrumentRef(
        symbol=symbol,
        name=meta.get("longName") or meta.get("shortName"),
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
        currency=meta.get("currency"),
        timezone=meta.get("exchangeTimezoneName"),
        kind=(meta.get("instrumentType") or None),
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
        import yfinance as yf

        self._yf = yf
        self.timeout = timeout
        # Raise errors instead of logging and returning empty frames.
        yf.config.debug.hide_exceptions = False
        yf.config.network.retries = 0  # MarketDesk applies its own bounded retry policy
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            yf.set_tz_cache_location(str(cache_dir))

    def cache_namespace(self) -> str:
        return "y"

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
            log.warning("yahoo %s failed: %s", what, name)
            kind = "timeout" if "Timeout" in name else "upstream_unavailable"
            raise ProviderError(kind, f"Yahoo {what} request failed ({name}).", retryable=True) from exc

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
            out.append(
                InstrumentRef(
                    symbol=str(sym).upper(),
                    name=item.get("longname") or item.get("shortname"),
                    exchange=item.get("exchDisp") or item.get("exchange"),
                    currency=None,  # Yahoo search does not report currency; resolved from the quote
                    timezone=None,
                    kind=qtype,
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
        symbol = self.validate_symbol(symbol)

        def run():
            info = self._yf.Ticker(symbol).info or {}
            if len(info) < 5:
                raise ProviderError("missing", "Yahoo returned no company information for this symbol.")
            return fundamentals_from_info(symbol, info)

        return self._call(run, "fundamentals")

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


__all__ = ["YahooProvider", "quote_from_history", "fundamentals_from_info", "normalize_dividend_yield"]

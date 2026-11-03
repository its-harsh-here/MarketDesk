"""Provider normalization (Yahoo responses mocked offline) and fixture determinism."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from marketdesk.config import REPO_ROOT
from marketdesk.providers.base import DailyBar, ProviderError, validate_bars
from marketdesk.providers.fixture import FixtureProvider, FixtureState
from marketdesk.providers.yahoo import (
    YahooProvider,
    fundamentals_from_info,
    normalize_dividend_yield,
    quote_from_history,
)


def frame(rows, tz="Asia/Kolkata"):
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz=tz) for d, *_ in rows])
    return pd.DataFrame([r[1:] for r in rows], index=idx, columns=["Open", "High", "Low", "Close", "Volume"])


META = {
    "regularMarketPrice": 1294.6,
    "regularMarketTime": pd.Timestamp("2026-11-03 10:30:26+0530"),
    "currency": "INR",
    "exchangeTimezoneName": "Asia/Kolkata",
    "fullExchangeName": "NSE",
    "longName": "Example Industries",
    "instrumentType": "EQUITY",
    "priceHint": 2,
    "regularMarketVolume": 123456,
    "regularMarketDayHigh": 1300.0,
    "regularMarketDayLow": 1280.25,
}


def test_quote_uses_previous_session_close_from_same_series():
    df = frame(
        [
            ("2026-10-30", 1170.4, 1180, 1160, 1175.5999755859375, 1000),
            ("2026-11-02", 1228.1, 1240, 1220, 1230.0999755859375, 2000),
            ("2026-11-03", 1287.9, 1300, 1280, 1294.5999755859375, 3000),  # current, incomplete session
        ]
    )
    q = quote_from_history("EXAMPLE.NS", df, META)
    assert q.last_price == Decimal("1294.60")
    assert q.previous_close == Decimal("1230.10")
    assert q.session_date == date(2026, 11, 3)
    assert q.market_time == datetime(2026, 11, 3, 5, 0, 26, tzinfo=UTC)
    assert q.change == Decimal("64.50")
    assert q.instrument.currency == "INR" and q.instrument.exchange == "NSE"
    assert "incomplete" in q.volume_note


def test_quote_without_market_time_is_missing_not_zero():
    with pytest.raises(ProviderError) as exc:
        quote_from_history("X.NS", frame([("2026-11-03", 1, 1, 1, 1, 1)]), {**META, "regularMarketPrice": None})
    assert exc.value.kind == "missing"


def test_index_volume_is_not_reported():
    q = quote_from_history("^NSEI", frame([("2026-11-02", 1, 2, 1, 1.5, 0)]), {**META, "instrumentType": "INDEX"})
    assert q.volume is None and q.recent_bars[0].volume is None


def test_bars_validation_sorts_dedupes_and_drops_bad_rows():
    bars = validate_bars(
        [
            DailyBar(date(2026, 1, 3), Decimal(1), Decimal(2), Decimal("0.5"), Decimal("1.5"), 1),
            DailyBar(date(2026, 1, 1), Decimal(1), Decimal(2), Decimal("0.5"), Decimal("1.5"), 1),
            DailyBar(
                date(2026, 1, 3), Decimal(1), Decimal(2), Decimal("0.5"), Decimal("1.7"), 1
            ),  # duplicate: last wins
            DailyBar(date(2026, 1, 2), Decimal(1), Decimal("0.9"), Decimal("0.5"), Decimal("1.5"), 1),  # high < close
            DailyBar(date(2026, 1, 4), None, None, None, Decimal("0"), None),  # non-positive close dropped
        ]
    )
    assert [b.session_date.day for b in bars] == [1, 2, 3]
    assert bars[2].close == Decimal("1.7")
    assert bars[1].open is None and bars[1].close == Decimal("1.5")  # inconsistent candle body removed


def test_dividend_yield_units_are_cross_checked():
    # yfinance 1.7 observed: dividendYield in percent points
    assert normalize_dividend_yield({"dividendYield": 6.02, "dividendRate": 16.0, "currentPrice": 266.8})[0] == Decimal(
        "6.02"
    )
    # legacy fraction form
    assert normalize_dividend_yield({"dividendYield": 0.0602, "dividendRate": 16.0, "currentPrice": 266.8})[
        0
    ] == Decimal("6.02")
    # unverifiable small value is withheld rather than guessed
    value, note = normalize_dividend_yield({"dividendYield": 0.5})
    assert value is None and "could not be verified" in note


def test_fundamentals_preserve_units_and_dates():
    f = fundamentals_from_info(
        "ITC.NS",
        {
            "marketCap": 3343514075136,
            "trailingPE": 16.790434,
            "dividendYield": 6.02,
            "dividendRate": 16.0,
            "currentPrice": 266.8,
            "fiftyTwoWeekHigh": 421.65,
            "fiftyTwoWeekLow": 252.8,
            "priceToBook": 4.610413,
            "mostRecentQuarter": 1782777600,
            "lastFiscalYearEnd": 1774915200,
            "currency": "INR",
            "financialCurrency": "INR",
            "longName": "Example Ltd",
        },
    )
    assert f.market_cap == Decimal("3343514075136")
    assert f.pe_ratio == Decimal("16.79") and f.price_to_book == Decimal("4.61")
    assert f.most_recent_quarter == date(2026, 6, 30) and f.last_fiscal_year_end == date(2026, 3, 31)


def test_yahoo_error_mapping_and_symbol_validation():
    yp = YahooProvider(timeout=1)
    from yfinance.exceptions import YFRateLimitError

    def boom():
        raise YFRateLimitError()

    with pytest.raises(ProviderError) as exc:
        yp._call(boom, "quote")
    assert exc.value.kind == "rate_limited" and exc.value.retryable

    def network():
        raise ConnectionError("reset")

    with pytest.raises(ProviderError) as exc:
        yp._call(network, "quote")
    assert exc.value.kind == "upstream_unavailable"
    with pytest.raises(ProviderError):
        yp.validate_symbol("SX:AURORA")
    with pytest.raises(ProviderError):
        yp.validate_symbol("rm -rf /")
    assert yp.validate_symbol(" reliance.ns ") == "RELIANCE.NS"
    assert yp.validate_symbol("^NSEI") == "^NSEI"


def test_fixture_provider_namespace_cursor_and_fault():
    state = {"s": FixtureState()}
    fp = FixtureProvider(REPO_ROOT / "fixtures", lambda: state["s"])
    assert fp.validate_symbol("aurora") == "SX:AURORA"
    with pytest.raises(ProviderError):
        fp.validate_symbol("RELIANCE.NS")
    assert fp.quote("SX:AURORA").last_price == Decimal("169.80")
    state["s"] = FixtureState(cursor_index=1)
    q = fp.quote("SX:AURORA")
    assert q.last_price == Decimal("173.90") and q.session_date == date(2026, 7, 1)
    assert q.market_time == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    state["s"] = FixtureState(cursor_index=1, fault=True)
    with pytest.raises(ProviderError) as exc:
        fp.quote("SX:AURORA")
    assert exc.value.kind == "upstream_unavailable"
    names = {i["name"] for i in fp.dataset.instruments.values()}
    assert all(not n.startswith(("Reliance", "Tata", "Infosys", "HDFC")) for n in names)


def test_fixture_dataset_regenerates_identically(tmp_path):
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_fixtures.py"), "--out", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    for name in ("daily_bars.csv", "instruments.json"):
        committed = hashlib.sha256((REPO_ROOT / "fixtures" / "market" / name).read_bytes()).hexdigest()
        regenerated = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        assert committed == regenerated, name


class _Resp:
    def __init__(self, code):
        self.status_code = code


class _HTTPError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.response = _Resp(code)


def test_http_status_codes_are_mapped():
    yp = YahooProvider(timeout=1)
    cases = {
        429: ("rate_limited", True),
        401: ("upstream_unavailable", False),
        403: ("upstream_unavailable", False),
        404: ("missing", False),
        503: ("upstream_unavailable", True),
    }
    for code, (kind, retryable) in cases.items():

        def boom(code=code):
            raise _HTTPError(code)

        with pytest.raises(ProviderError) as exc:
            yp._call(boom, "fundamentals")
        assert (exc.value.kind, exc.value.retryable) == (kind, retryable), code
        assert f"HTTP {code}" in exc.value.message


def test_fundamentals_are_derived_when_company_summary_is_refused():
    import types

    calls = {"info": 0}
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz="Asia/Kolkata") for d in ("2026-06-04", "2026-06-05", "2026-11-03")])
    df = pd.DataFrame(
        {
            "Open": [100, 101, 120],
            "High": [102, 103, 125],
            "Low": [99, 100, 118],
            "Close": [101, 102, 120],
            "Volume": [10, 10, 10],
            "Dividends": [0.0, 6.0, 0.0],
        },
        index=idx,
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.history_metadata = {
                **META,
                "regularMarketPrice": 120.0,
                "fiftyTwoWeekHigh": 130.0,
                "fiftyTwoWeekLow": 90.0,
            }

        @property
        def info(self):
            calls["info"] += 1
            raise _HTTPError(401)

        def history(self, **kwargs):
            return df

        def get_valuation_measures(self, freq):
            return pd.DataFrame(
                {"Current": [1.5e12, 21.104, 1.744]}, index=["Market Cap", "Trailing P/E", "Price/Book"]
            )

        def get_income_stmt(self, freq):
            when = "2026-09-30" if freq == "quarterly" else "2026-03-31"
            return pd.DataFrame(columns=[pd.Timestamp(when)])

    class FakeSearch:
        def __init__(self, *args, **kwargs):
            self.quotes = [{"symbol": "EXAMPLE.NS", "sectorDisp": "Energy", "industryDisp": "Refining"}]

    yp = YahooProvider(timeout=1)
    yp._yf = types.SimpleNamespace(Ticker=FakeTicker, Search=FakeSearch)
    f = yp.fundamentals("EXAMPLE.NS")
    assert (
        f.market_cap == Decimal("1500000000000")
        and f.pe_ratio == Decimal("21.10")
        and f.price_to_book == Decimal("1.74")
    )
    assert f.dividend_yield_percent == Decimal("5.00")  # 6 paid in last 12 months / 120
    assert (f.fifty_two_week_low, f.fifty_two_week_high) == (Decimal("90.00"), Decimal("130.00"))
    assert f.most_recent_quarter == date(2026, 9, 30) and f.last_fiscal_year_end == date(2026, 3, 31)
    assert (f.sector, f.industry) == ("Energy", "Refining")
    assert "HTTP 401" in f.notes[0] and any("12 months" in n for n in f.notes)
    yp.fundamentals("EXAMPLE.NS")
    assert calls["info"] == 1  # the refused endpoint is not retried on every request


def test_not_found_body_means_missing_whatever_the_status():
    yp = YahooProvider(timeout=1)

    class Resp:
        status_code = 401
        text = '{"quoteSummary":{"result":null,"error":{"code":"Not Found","description":"Quote not found"}}}'

    class Err(Exception):
        response = Resp()

    def boom():
        raise Err()

    with pytest.raises(ProviderError) as exc:
        yp._call(boom, "quote")
    assert exc.value.kind == "missing" and not exc.value.retryable

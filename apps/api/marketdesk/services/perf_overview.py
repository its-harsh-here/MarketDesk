"""Performance overview (a quote-page staple): price return over standard periods against the market benchmark,
plus the 52-week range. Price return only — the provider's closes are split-adjusted, dividends are not added."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from marketdesk.models import Instrument
from marketdesk.services.market import MarketDataService

PERIODS: tuple[tuple[str, str], ...] = (
    ("1W", "1 week"),
    ("1M", "1 month"),
    ("3M", "3 months"),
    ("6M", "6 months"),
    ("YTD", "Year to date"),
    ("1Y", "1 year"),
    ("3Y", "3 years"),
    ("5Y", "5 years"),
)


def start_for(code: str, end: date) -> date:
    if code == "YTD":
        return date(end.year - 1, 12, 31)  # last close of the previous year
    n, unit = int(code[:-1]), code[-1]
    return end - (
        timedelta(weeks=n) if unit == "W" else relativedelta(months=n) if unit == "M" else relativedelta(years=n)
    )


def close_on_or_before(closes: list[tuple[date, Decimal]], day: date) -> tuple[date, Decimal] | None:
    best = None
    for d, c in closes:  # ascending
        if d > day:
            break
        best = (d, c)
    return best


def period_returns(closes: list[tuple[date, Decimal]]) -> dict[str, dict]:
    """{code: {start, start_close, return_pct, annualized_pct}} from ascending (date, close); null with a reason
    when the history does not reach back to the period's start (within 7 days)."""
    if len(closes) < 2:
        return {c: {"return_pct": None, "why": "Not enough history."} for c, _ in PERIODS}
    end_d, end_c = closes[-1]
    out = {}
    for code, _ in PERIODS:
        target = start_for(code, end_d)
        base = close_on_or_before(closes, target)
        if base is None or (target - base[0]).days > 7 or base[1] <= 0:
            out[code] = {"return_pct": None, "why": f"History does not reach back to {target.isoformat()}."}
            continue
        r = end_c / base[1] - 1
        row = {"start": base[0].isoformat(), "start_close": base[1], "return_pct": r * 100, "why": None}
        years = int(code[:-1]) if code.endswith("Y") and code != "YTD" else 0
        if years >= 3:
            row["annualized_pct"] = (Decimal(float(end_c / base[1]) ** (1 / years)) - 1) * 100
        out[code] = row
    return out


def range_52w(closes: list[tuple[date, Decimal]]) -> dict | None:
    if not closes:
        return None
    end_d, end_c = closes[-1]
    win = [(d, c) for d, c in closes if d > end_d - relativedelta(years=1)]
    hi = max(win, key=lambda x: x[1])
    lo = min(win, key=lambda x: x[1])
    return {"high": hi[1], "high_date": hi[0].isoformat(), "low": lo[1], "low_date": lo[0].isoformat(),
            "from_high_pct": (end_c / hi[1] - 1) * 100, "from_low_pct": (end_c / lo[1] - 1) * 100,
            "basis": "daily closes"}  # fmt: skip


async def _series(market: MarketDataService, symbol: str):
    h = await market.history(symbol, "5Y")
    bars = h.value.bars if h.value else []
    return [(b.session_date, b.close) for b in bars if b.close is not None], h


async def overview(market: MarketDataService, settings, inst: Instrument) -> dict:
    from marketdesk.services.security_risk import _default_benchmark

    bench = _default_benchmark(settings, market, inst)
    (own, h), (bclose, bh) = await asyncio.gather(_series(market, inst.symbol), _series(market, bench))
    if not own:
        return {"symbol": inst.symbol, "status": "missing", "reason": h.meta.message or "No price history."}
    mine = period_returns(own)
    theirs = period_returns(bclose) if bclose else {}
    rows = []
    for code, label in PERIODS:
        b = theirs.get(code) or {}
        m = mine[code]
        rows.append({"code": code, "label": label, **m, "benchmark_pct": b.get("return_pct"),
                     "benchmark_annualized_pct": b.get("annualized_pct"),
                     "relative_pct": (m["return_pct"] - b["return_pct"])
                     if m.get("return_pct") is not None and b.get("return_pct") is not None else None})  # fmt: skip
    bref = bh.value.instrument if bh.value else None
    return {
        "symbol": inst.symbol,
        "status": h.meta.status,
        "as_of": own[-1][0].isoformat(),
        "benchmark": {
            "symbol": bench,
            "name": bref.name if bref else None,
            "as_of": bclose[-1][0].isoformat() if bclose else None,
            "why": None if bclose else (bh.meta.message or "No benchmark prices."),
        },  # fmt: skip
        "rows": rows,
        "range_52w": range_52w(own),
        "basis": (h.value.adjustment if h.value else None) or "Provider daily closes.",
        "note": "Price return from daily closes (dividends not included). Periods end at the latest close; the "
        "start is the last close on or before the same calendar day earlier (YTD: the last close of the previous "
        "year). 3- and 5-year figures are also shown per year (compound).",
    }

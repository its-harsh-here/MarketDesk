"""Terminal T8: a per-security context strip — the market benchmark, the listing currency, rates and commodities
next to the security, each with its latest level, 1-day and 1-month change, and the correlation of its daily changes
with the security's over the last year (aligned dates only; a description of co-movement, not a cause)."""

from __future__ import annotations

import asyncio
import math
from datetime import timedelta

from marketdesk.models import Instrument
from marketdesk.services import earnings as er
from marketdesk.services.market import MarketDataService


def related(inst: Instrument, source: str, benchmark: str) -> list[tuple[str, str, str]]:
    """(symbol, label, kind) — kind "yield" changes are in percentage points."""
    if source == "fixture":
        return [(benchmark, "Market benchmark", "level"), ("SX:USDINR", "USD/INR (sample)", "level")]
    rows = [(benchmark, "Market benchmark", "level")]
    if er.is_india(inst):
        rows += [("USDINR=X", "US dollar in rupees", "level"), ("^INDIAVIX", "India VIX", "level")]
    else:
        rows += [("DX-Y.NYB", "US dollar index", "level"), ("^VIX", "CBOE VIX", "level")]
    rows += [
        ("^TNX", "US 10-year Treasury yield", "yield"),
        ("BZ=F", "Brent crude", "level"),
        ("GC=F", "Gold", "level"),
    ]
    return rows


def correlation(a: dict, b: dict, min_n: int = 60) -> tuple[float | None, int]:
    """Pearson correlation of day-on-day changes on the dates both series have (consecutive common dates)."""
    days = sorted(set(a) & set(b))
    ra, rb = [], []
    for d0, d1 in zip(days, days[1:], strict=False):
        if a[d0] and b[d0]:
            ra.append(float(a[d1] / a[d0] - 1))
            rb.append(float(b[d1] / b[d0] - 1))
    n = len(ra)
    if n < min_n:
        return None, n
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    return (cov / math.sqrt(va * vb) if va and vb else None), n


def changes(closes: dict, kind: str) -> dict:
    days = sorted(closes)
    if len(days) < 2:
        return {"d1": None, "m1": None}
    last = closes[days[-1]]

    def diff(then):
        if then is None:
            return None
        return float(last - then) if kind == "yield" else (float(last / then - 1) * 100 if then else None)

    target = days[-1] - timedelta(days=30)
    m1 = [d for d in days if d <= target]
    return {"d1": diff(closes[days[-2]]), "m1": diff(closes[m1[-1]]) if m1 else None}


async def context(market: MarketDataService, settings, inst: Instrument) -> dict:
    from marketdesk.services.security_risk import _default_benchmark

    rows = related(inst, market.source, _default_benchmark(settings, market, inst))
    hists = await asyncio.gather(market.history(inst.symbol, "1Y"), *(market.history(s, "1Y") for s, _, _ in rows))
    own = {b.session_date: b.close for b in (hists[0].value.bars if hists[0].value else [])}
    out = []
    for (sym, label, kind), h in zip(rows, hists[1:], strict=True):
        closes = {b.session_date: b.close for b in (h.value.bars if h.value else [])}
        if not closes:
            out.append(
                {"symbol": sym, "label": label, "kind": kind, "value": None, "why": h.meta.message or "No prices."}
            )
            continue
        corr, n = correlation(own, closes)
        last_day = max(closes)
        out.append({"symbol": sym, "label": label, "kind": kind, "value": format(closes[last_day], "f"),
                    "as_of": last_day.isoformat(), **changes(closes, kind), "correlation": corr, "n": n,
                    "status": h.meta.status})  # fmt: skip
    return {
        "symbol": inst.symbol,
        "items": out,
        "note": "Daily closes from the price provider. Correlation of day-on-day changes over the last year on dates "
        "both series traded (shown with at least 60 pairs); it describes co-movement, not cause. Yields change in "
        "percentage points.",
    }

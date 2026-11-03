"""Normalized price comparison of up to three instruments (pure calculation + payload assembly).

Method: each series is rebased to 100 on the first date on which every instrument has a daily bar, and only dates
present in all series are kept (calendars differ: an Indian holiday is a US trading day and vice versa). Values are
price returns in each instrument's own currency on the provider's adjustment basis (Yahoo: split-adjusted, dividends
not reinvested), so they are not total returns and no currency conversion is applied.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from marketdesk.services.market import MarketDataService

MAX_COMPARE = 3
METHOD = (
    "Rebased to 100 on the first common date; only dates on which every instrument has a daily close are shown. "
    "Price return in each instrument's own currency, no currency conversion; dividends are not included."
)


def align_and_rebase(series: dict[str, list[tuple[date, Decimal]]]) -> dict:
    """series: symbol -> [(session_date, close)]. Returns common dates, rebased values and excluded-date counts."""
    by_symbol = {s: {d: c for d, c in pts if c is not None and c > 0} for s, pts in series.items()}
    common = sorted(set.intersection(*(set(m) for m in by_symbol.values()))) if by_symbol else []
    excluded = {s: len(m) - len(common) for s, m in by_symbol.items()}
    if len(common) < 2:
        return {"dates": [], "values": {s: [] for s in series}, "excluded": excluded, "base_date": None}
    base = common[0]
    values = {
        s: [(m[d] / m[base] * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for d in common]
        for s, m in by_symbol.items()
    }
    return {"dates": common, "values": values, "excluded": excluded, "base_date": base}


async def compare_payload(market: MarketDataService, symbols: list[str], range_: str) -> dict:
    results = await asyncio.gather(*(market.history(s, range_) for s in symbols))
    usable: dict[str, list[tuple[date, Decimal]]] = {}
    items = []
    for sym, res in zip(symbols, results, strict=True):
        h = res.value
        inst = h.instrument if h else None
        items.append(
            {
                "symbol": sym,
                "name": inst.name if inst else None,
                "currency": inst.currency if inst else None,
                "exchange": inst.exchange if inst else None,
                "country": inst.country if inst else None,
                "adjustment": h.adjustment if h else None,
                "bars": len(h.bars) if h else 0,
                "meta": res.meta.to_dict(),
            }
        )
        if h and h.bars:
            usable[sym] = [(b.session_date, b.close) for b in h.bars]
    aligned = align_and_rebase(usable) if len(usable) == len(symbols) else None
    for item in items:
        item["excluded_dates"] = aligned["excluded"].get(item["symbol"]) if aligned else None
    return {
        "range": range_,
        "method": METHOD,
        "base_date": aligned["base_date"] if aligned else None,
        "dates": aligned["dates"] if aligned else [],
        "series": {s: aligned["values"][s] for s in symbols} if aligned and aligned["dates"] else {},
        "instruments": items,
        "complete": bool(aligned and aligned["dates"]),
        "currencies_differ": len({i["currency"] for i in items if i["currency"]}) > 1,
    }

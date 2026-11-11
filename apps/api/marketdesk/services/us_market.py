"""Market-wide US movers and most-active stocks from Alpaca's screener (docs/DECISIONS.md #67).

Alpaca's screener ranks every US-listed security, so the raw lists are dominated by warrants, rights and sub-dollar
shares. This view keeps common-looking tickers (1–5 letters, optional class suffix) priced at $5 or more, and says
so. Prices and changes are Alpaca's; most-active prices come from IEX snapshots (single exchange) and are labelled.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from marketdesk.providers.base import ProviderError

MIN_PRICE = 5.0
_COMMON = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def _keep(row: dict) -> bool:
    price = row.get("price")
    return (
        isinstance(row.get("symbol"), str)
        and bool(_COMMON.match(row["symbol"]))
        # Nasdaq's fifth-letter convention: W warrant, R rights, U units
        and not (len(row["symbol"]) == 5 and row["symbol"][-1] in "WRU")
        and isinstance(price, (int, float))
        and price >= MIN_PRICE
    )


def filter_movers(raw: dict, limit: int = 15) -> dict:
    """Pure: Alpaca movers payload → filtered gainers/losers."""

    def rows(key: str) -> list[dict]:
        out = []
        for r in raw.get(key) or []:
            if isinstance(r, dict) and _keep(r):
                out.append({"symbol": r["symbol"], "price": r["price"], "change": r.get("change"),
                            "change_pct": r.get("percent_change")})  # fmt: skip
        return out[:limit]

    return {"gainers": rows("gainers"), "losers": rows("losers"), "as_of": raw.get("last_updated")}


def actives_view(raw: dict, snaps: dict, limit: int = 15) -> list[dict]:
    """Pure: most-active by volume, joined to IEX snapshots for price and change vs the previous close."""
    out = []
    for r in raw.get("most_actives") or []:
        sym = r.get("symbol") if isinstance(r, dict) else None
        s = snaps.get(sym) if isinstance(snaps, dict) and sym else None
        if not isinstance(s, dict):
            continue
        price = (s.get("latestTrade") or {}).get("p")
        prev = (s.get("prevDailyBar") or {}).get("c")
        row = {"symbol": sym, "price": price, "volume": r.get("volume"), "trades": r.get("trade_count")}
        if not _keep(row):
            continue
        row["change_pct"] = ((price - prev) / prev * 100) if isinstance(prev, (int, float)) and prev else None
        out.append(row)
    return out[:limit]


async def us_movers(alpaca) -> dict:
    base = {
        "source": "Market screener (all US-listed stocks)",
        "filter": f"Common-stock tickers priced at ${MIN_PRICE:.0f} or more; warrants, rights and penny shares are "
        "left out.",
    }
    if alpaca is None or not alpaca.enabled:
        why = "Market-wide US movers are not configured on this server."
        return {**base, "status": "not_configured", "reason": why}
    try:
        movers, actives = await asyncio.gather(
            asyncio.to_thread(alpaca.movers, 50), asyncio.to_thread(alpaca.most_actives, 50)
        )
        syms = [r.get("symbol") for r in actives.get("most_actives") or [] if isinstance(r, dict)]
        snaps = await asyncio.to_thread(alpaca.snapshots_stock, [s for s in syms if s])
    except ProviderError as err:
        return {**base, "status": "unavailable", "reason": err.message}
    m = filter_movers(movers)
    return {
        **base,
        "status": "available",
        "as_of": m["as_of"],
        "fetched_at": datetime.now(UTC).isoformat(),
        "gainers": m["gainers"],
        "losers": m["losers"],
        "actives": actives_view(actives, snaps),
        "note": "Percent change is from the previous close as the screener reports it. Most-active prices are "
        "the latest single-exchange (IEX) trade. A list of movers is a description of today's prices, not a "
        "recommendation.",
    }

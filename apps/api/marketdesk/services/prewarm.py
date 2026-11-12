"""Pre-warm the data behind the owner's watchlist and holdings (docs/PERFORMANCE_ROADMAP.md 3.1).

Each worker cycle refreshes, for a few watchlist/holdings symbols at a time (round-robin), the market data their
pages open with — daily history for the default chart range, fundamentals, corporate actions and headlines. The
market service's own cache rules apply: anything still fresh is not fetched again, and heavy payloads land in the
database cache, not in memory. Opening those pages then reads the cache instead of waiting on providers.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from marketdesk.services.screener import resolve_universe

log = logging.getLogger("marketdesk.worker")
PER_CYCLE = 6
_cursor = {"i": 0}


def symbols(db: Session, provider: str, limit: int = 120) -> list[str]:
    seen: dict[str, None] = {}
    for spec in ({"kind": "watchlists"}, {"kind": "holdings"}):
        for inst in resolve_universe(db, provider, spec, limit)["instruments"]:
            seen.setdefault(inst.symbol, None)
    return list(seen)


async def warm_macro(db: Session, market) -> dict:
    """The Macro page's watchboard (market series) and official statistics (FRED), both cached for hours."""
    from datetime import UTC, datetime

    from marketdesk.providers.fred import FredClient
    from marketdesk.services.macro import watchboard
    from marketdesk.services.official import official

    out = {}
    try:
        await watchboard(market)
        out["watchboard"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["watchboard"] = type(exc).__name__
    fred = FredClient(market.settings.fred_api_key)
    if fred.enabled:
        try:
            await official(db, fred, datetime.now(UTC).date())
            out["official"] = "ok"
        except Exception as exc:  # noqa: BLE001
            out["official"] = type(exc).__name__
    return out


async def warm(db: Session, market, per_cycle: int = PER_CYCLE) -> dict:
    macro = await warm_macro(db, market)
    syms = symbols(db, market.source)
    if not syms:
        return {"symbols": 0, "macro": macro}
    start = _cursor["i"] % len(syms)
    batch = (syms[start:] + syms[:start])[: min(per_cycle, len(syms))]
    _cursor["i"] = start + len(batch)
    fetched = failed = 0
    for sym in batch:
        for call in (lambda s=sym: market.history(s, "6M"), lambda s=sym: market.fundamentals(s),
                     lambda s=sym: market.actions(s), lambda s=sym: market.news(s)):  # fmt: skip
            try:
                r = await call()
                fetched += r.meta.status == "available"  # a fresh fetch (cached answers cost nothing)
                failed += r.value is None
            except Exception:  # noqa: BLE001 - warming must never break the worker cycle
                failed += 1
    return {"symbols": len(syms), "warmed": batch, "fetched": fetched, "failed": failed, "macro": macro}

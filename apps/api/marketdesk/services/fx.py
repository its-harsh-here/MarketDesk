"""Valuation FX: current rates used only to display balances in a base currency.

A valuation rate never rewrites a transaction, never changes an account's native amounts, and is shown with its
source, market time and status. Without a usable rate the consolidated total is withheld (labelled incomplete).
Historical returns would need historical rates; none are computed here.
"""

from __future__ import annotations

from decimal import Decimal

from marketdesk.services.market import MarketDataService

USABLE = {"sample", "available", "cached", "stale"}


def fx_symbol(source: str, base: str, quote: str) -> str | None:
    """Provider symbol quoting `quote` units per 1 `base` (e.g. INR per USD)."""
    if source == "fixture":
        return "SX:USDINR" if (base, quote) == ("USD", "INR") else None
    if source == "yahoo":
        return f"{base}{quote}=X"
    return None


async def valuation_rate(market: MarketDataService, base: str, quote: str) -> dict:
    """{pair, rate, status, market_time, fetched_at, source, symbol, message}; rate None when unusable."""
    pair = f"{base}/{quote}"
    if base == quote:
        return {"pair": pair, "rate": Decimal(1), "status": "identity", "source": None, "symbol": None}
    symbol = fx_symbol(market.source, base, quote)
    if symbol is None:
        return {"pair": pair, "rate": None, "status": "unsupported", "message": "No rate source for this pair."}
    r = await market.quote(symbol)
    q = r.value
    ok = q is not None and r.meta.status in USABLE and q.last_price > 0 and q.instrument.currency == quote
    return {
        "pair": pair,
        "rate": q.last_price if ok else None,
        "status": r.meta.status if ok or q is None else "invalid",
        "market_time": q.market_time if q is not None else None,
        "fetched_at": r.meta.fetched_at,
        "source": r.meta.source,
        "symbol": symbol,
        "message": r.meta.message if not ok else ("Synthetic sample rate." if market.source == "fixture" else None),
    }

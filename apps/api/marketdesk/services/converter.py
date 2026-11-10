"""Currency converter: an amount at the provider's latest quoted rate (direct pair, or the inverse of the reverse
pair), shown with its source, market time and status. Indicative only — not a dealing rate; no fees or spread."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from marketdesk.services.fx import valuation_rate
from marketdesk.services.market import MarketDataService

CURRENCIES = ("INR", "USD", "EUR", "GBP", "JPY", "AED", "SGD", "CAD", "AUD", "CHF", "CNY", "HKD")
FIXTURE_CURRENCIES = ("INR", "USD")
PLACES = {"JPY": 0}


def sig(x: Decimal | None, digits: int = 8) -> str | None:
    """A rate as a string with `digits` significant digits (small rates such as INR→USD keep their precision)."""
    return None if x is None else format(x, f".{digits}g") if x < 1 else format(x.quantize(Decimal("0.000001")), "f")


def quantize(amount: Decimal, ccy: str) -> Decimal:
    return amount.quantize(Decimal(1).scaleb(-PLACES.get(ccy, 2)), rounding=ROUND_HALF_UP)


async def convert(market: MarketDataService, amount: Decimal, base: str, quote: str) -> dict:
    allowed = FIXTURE_CURRENCIES if market.source == "fixture" else CURRENCIES
    if base not in allowed or quote not in allowed:
        return {
            "status": "unsupported",
            "message": f"Supported currencies: {', '.join(allowed)}.",
            "currencies": allowed,
        }
    r = await valuation_rate(market, base, quote)
    inverted = False
    if r.get("rate") is not None and r["rate"] < Decimal("0.1") and base != quote:
        # Small rates (INR→EUR ≈ 0.0095) are quoted to few decimals; the reverse pair carries more precision.
        rev = await valuation_rate(market, quote, base)
        if rev.get("rate"):
            r = {**rev, "pair": f"{base}/{quote}", "rate": Decimal(1) / rev["rate"]}
            inverted = True
    if r.get("rate") is None and base != quote:
        rev = await valuation_rate(market, quote, base)
        if rev.get("rate"):
            r = {**rev, "pair": f"{base}/{quote}", "rate": Decimal(1) / rev["rate"]}
            inverted = True
    rate = r.get("rate")
    out = {
        "from": base,
        "to": quote,
        "amount": format(amount, "f"),
        "rate": sig(rate),
        "inverse": sig(Decimal(1) / rate) if rate else None,
        "result": format(quantize(amount * rate, quote), "f") if rate else None,
        "status": r.get("status"),
        "market_time": r.get("market_time"),
        "fetched_at": r.get("fetched_at"),
        "source": r.get("source"),
        "symbol": r.get("symbol"),
        "inverted": inverted,
        "message": r.get("message"),
        "currencies": allowed,
        "note": "Indicative: the provider's latest quoted rate, not a dealing rate (no spread or fees)."
        + (" Derived from the reverse pair." if inverted else ""),
    }
    return out

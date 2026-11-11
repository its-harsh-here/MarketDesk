"""Dividend summary (a quote-page staple): trailing-12-month dividends per share and yield, payments per year,
calendar-year totals and growth, from the price provider's dividend records (amounts per share as the provider
reports them; split-adjusted by Yahoo). Yield uses the latest quote; nothing is forecast."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from marketdesk.services.fx import USABLE
from marketdesk.services.market import MarketDataService

PER_YEAR = {"monthly": 12, "quarterly": 4, "semi-annual": 2, "annual": 1}


def _indicated(last: Decimal, freq: str, price: Decimal | None) -> dict | None:
    """Latest payment × the payments a year implied by the frequency (what quote pages call the forward dividend);
    not computed for irregular payers."""
    n = PER_YEAR.get(freq)
    if n is None:
        return None
    total = last * n
    return {"total": total, "per_year": n, "yield_pct": (total / price * 100) if price and price > 0 else None}


def summary(divs: list[tuple[date, Decimal]], today: date, price: Decimal | None) -> dict:
    """divs: (ex-date, amount per share), any order."""
    divs = sorted((d, a) for d, a in divs if a > 0)
    if not divs:
        return {"status": "none", "why": "The provider reports no dividends for this listing."}
    ttm_from = today - timedelta(days=365)
    ttm = [a for d, a in divs if d > ttm_from and d <= today]
    ttm_total = sum(ttm, Decimal(0))
    two_y = [d for d, _ in divs if d > today - timedelta(days=730) and d <= today]
    per_year = len(two_y) / 2 if two_y else 0
    freq = ("monthly" if per_year >= 10 else "quarterly" if per_year >= 3.5 else "semi-annual" if per_year >= 1.75
            else "annual" if per_year >= 0.75 else "irregular")  # fmt: skip
    by_year: dict[int, Decimal] = {}
    for d, a in divs:
        by_year[d.year] = by_year.get(d.year, Decimal(0)) + a
    complete = sorted(y for y in by_year if y < today.year)  # the current year is incomplete
    years = [
        {"year": y, "total": by_year[y], "payments": sum(1 for d, _ in divs if d.year == y)} for y in sorted(by_year)
    ]
    growth = None
    if len(complete) >= 6 and by_year[complete[-6]] > 0:
        ratio = float(by_year[complete[-1]] / by_year[complete[-6]])
        growth = {"years": 5, "from": complete[-6], "to": complete[-1], "cagr_pct": (Decimal(ratio**0.2) - 1) * 100}
    streak = 0
    for y in reversed(complete):
        prev = by_year.get(y - 1)
        if prev is not None and by_year[y] > prev:
            streak += 1
        else:
            break
    return {
        "status": "available",
        "last": {"ex_date": divs[-1][0].isoformat(), "amount": divs[-1][1]},
        "ttm": {
            "total": ttm_total,
            "payments": len(ttm),
            "from": ttm_from.isoformat(),
            "yield_pct": (ttm_total / price * 100) if price and price > 0 and ttm_total > 0 else None,
        },  # fmt: skip
        "frequency": freq,
        "indicated": _indicated(divs[-1][1], freq, price),
        "payments_per_year": per_year,
        "years": years[-12:],
        "growth_5y": growth,
        "increase_streak_years": streak,
    }


async def dividend_summary(market: MarketDataService, symbol: str, today: date) -> dict:
    acts, quote = await market.actions(symbol), await market.quote(symbol)
    if acts.value is None:
        return {"symbol": symbol, "status": "unavailable", "why": acts.meta.message or "No corporate actions."}
    price = quote.value.last_price if quote.value is not None and quote.meta.status in USABLE else None
    divs = [(a.action_date, a.value) for a in acts.value if a.kind == "DIVIDEND"]
    out = summary(divs, today, price)
    return {
        "symbol": symbol,
        **out,
        "price": price,
        "currency": quote.value.instrument.currency if quote.value else None,
        "source": f"{market.source} corporate actions",
        "note": "Amounts per share as the provider reports them (ex-dates). Trailing yield = dividends with ex-dates "
        "in the last 365 days ÷ the latest price. Indicated = latest payment × payments a year (a convention, "
        "not a forecast). Growth uses complete calendar years only.",
    }

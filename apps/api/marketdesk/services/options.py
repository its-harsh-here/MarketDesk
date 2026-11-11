"""Terminal T7: read-only option chain analytics.

From one expiry of the provider's chain: open interest and volume by side, put/call ratios, max pain (the strike at
which option holders' total intrinsic value at expiry would be smallest), at-the-money implied volatility, and the
volatility smile. Descriptive statistics of the chain only — no strategy, pricing model or recommendation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from marketdesk.services import earnings as er
from marketdesk.services.market import MarketDataService


def ratio(a: int, b: int) -> Decimal | None:
    return (Decimal(a) / Decimal(b)) if b else None


def max_pain(calls: list, puts: list) -> Decimal | None:
    """Strike minimising Σ OI_call·max(0, S−K) + Σ OI_put·max(0, K−S) over the listed strikes."""
    strikes = sorted({o.strike for o in calls} | {o.strike for o in puts})
    if not strikes:
        return None

    def payout(s: Decimal) -> Decimal:
        c = sum((Decimal(o.open_interest or 0) * max(Decimal(0), s - o.strike) for o in calls), Decimal(0))
        p = sum((Decimal(o.open_interest or 0) * max(Decimal(0), o.strike - s) for o in puts), Decimal(0))
        return c + p

    return min(strikes, key=lambda s: (payout(s), s))


def atm(calls: list, puts: list, spot: Decimal | None) -> dict | None:
    if spot is None:
        return None
    strikes = sorted({o.strike for o in calls} & {o.strike for o in puts})
    if not strikes:
        return None
    k = min(strikes, key=lambda s: abs(s - spot))
    ivs = [o.implied_vol for o in (*calls, *puts) if o.strike == k and o.implied_vol]
    return {"strike": k, "iv": (sum(ivs, Decimal(0)) / len(ivs)) if ivs else None}


def analytics(chain, spot: Decimal | None) -> dict:
    c_oi = sum(o.open_interest or 0 for o in chain.calls)
    p_oi = sum(o.open_interest or 0 for o in chain.puts)
    c_v = sum(o.volume or 0 for o in chain.calls)
    p_v = sum(o.volume or 0 for o in chain.puts)
    return {
        "calls": {"open_interest": c_oi, "volume": c_v},
        "puts": {"open_interest": p_oi, "volume": p_v},
        "put_call_oi": ratio(p_oi, c_oi),
        "put_call_volume": ratio(p_v, c_v),
        "max_pain": max_pain(chain.calls, chain.puts),
        "atm": atm(chain.calls, chain.puts, spot),
        "smile": [
            {"strike": o.strike, "side": side, "iv": o.implied_vol}
            for side, rows in (("call", chain.calls), ("put", chain.puts))
            for o in rows
            if o.implied_vol
        ],  # fmt: skip
    }


def _row(o) -> dict:
    return {
        "contract": o.contract, "strike": o.strike, "last": o.last, "bid": o.bid, "ask": o.ask, "volume": o.volume,
        "open_interest": o.open_interest, "iv": o.implied_vol, "itm": o.in_the_money,
        "last_trade": o.last_trade.isoformat() if o.last_trade else None,
    }  # fmt: skip


async def chain_view(market: MarketDataService, inst, expiry: date | None) -> dict:
    if er.is_india(inst):
        why = "Indian F&O chains (NSE) need verified terms before they can be fetched; none are shown."
        return {"symbol": inst.symbol, "status": "not_available", "reason": why}
    r, q = await market.options(inst.symbol, expiry), await market.quote(inst.symbol)
    if r.value is None:
        return {"symbol": inst.symbol, "status": r.meta.status, "reason": r.meta.message or "No option chain."}
    c = r.value
    spot = q.value.last_price if q.value is not None else None
    return {
        "symbol": inst.symbol,
        "status": r.meta.status,
        "source": c.source,
        "fetched_at": r.meta.fetched_at.isoformat() if r.meta.fetched_at else None,
        "expiries": [d.isoformat() for d in c.expiries],
        "expiry": c.expiry.isoformat(),
        "days_to_expiry": (c.expiry - datetime.now(UTC).date()).days,
        "currency": c.currency,
        "spot": spot,
        "spot_time": q.value.market_time.isoformat() if q.value is not None else None,
        "calls": [_row(o) for o in c.calls],
        "puts": [_row(o) for o in c.puts],
        "stats": analytics(c, spot),
        "note": "Read-only, delayed provider data (bid/ask and last trade as reported; implied volatility is the "
        "provider's). Put/call ratios and max pain describe this expiry's open interest; they are not forecasts.",
    }

"""Terminal T9: movers monitor across a declared universe (all watchlists, one watchlist, a list or holdings).

From each member's latest provider quote: biggest gainers and losers against the previous close, most active by
traded value, unusual volume (the latest completed session against the median of the twenty before it), and
breadth. Volume for a session still trading is labelled as partial and is never compared with full sessions.
"""

from __future__ import annotations

from decimal import Decimal
from statistics import median

from sqlalchemy.orm import Session

from marketdesk.services.market import MarketDataService

EXCLUDED_KINDS = {"INDEX", "CURRENCY"}
MAX_MEMBERS = 80
TOP = 8


def volume_ratio(bars: list) -> dict | None:
    """Latest completed bar's volume against the median of up to 20 earlier completed bars (needs 10)."""
    vols = [(b.session_date, b.volume) for b in bars if b.volume]
    if len(vols) < 11:
        return None
    last_date, last = vols[-1]
    base = [v for _, v in vols[-21:-1]]
    med = median(base)
    if not med:
        return None
    return {"session": last_date.isoformat(), "volume": last, "median": med, "n": len(base),
            "ratio": round(last / med, 2)}  # fmt: skip


def row_for(inst, res) -> dict:
    q = res.value
    meta = res.meta
    out = {"symbol": inst.symbol, "name": inst.name, "currency": inst.currency, "kind": inst.kind,
           "status": meta.status, "message": meta.message}  # fmt: skip
    if q is None:
        return out
    pct = q.change_percent
    traded = (q.last_price * Decimal(q.volume)) if q.volume else None
    completed = [b for b in q.recent_bars if q.session_date is None or b.session_date < q.session_date]
    return {
        **out,
        "last": q.last_price,
        "change": q.change,
        "change_pct": pct,
        "volume": q.volume,
        "volume_note": q.volume_note,
        "traded_value": traded,
        "session": q.session_date.isoformat() if q.session_date else None,
        "market_time": q.market_time.isoformat(),
        "unusual": volume_ratio(completed),
        "range_pos": (
            float((q.last_price - q.day_low) / (q.day_high - q.day_low))
            if q.day_high is not None and q.day_low is not None and q.day_high > q.day_low
            else None
        ),
    }


def rank(rows: list[dict]) -> dict:
    priced = [r for r in rows if r.get("change_pct") is not None]
    by_pct = sorted(priced, key=lambda r: r["change_pct"], reverse=True)
    gainers = [r for r in by_pct if r["change_pct"] > 0][:TOP]
    losers = [r for r in reversed(by_pct) if r["change_pct"] < 0][:TOP]
    active = sorted((r for r in rows if r.get("traded_value")), key=lambda r: r["traded_value"], reverse=True)[:TOP]
    unusual = sorted((r for r in rows if r.get("unusual") and r["unusual"]["ratio"] >= 1.5),
                     key=lambda r: r["unusual"]["ratio"], reverse=True)[:TOP]  # fmt: skip
    adv = sum(1 for r in priced if r["change_pct"] > 0)
    dec = sum(1 for r in priced if r["change_pct"] < 0)
    return {
        "gainers": gainers,
        "losers": losers,
        "active": active,
        "unusual": unusual,
        "breadth": {
            "advancing": adv,
            "declining": dec,
            "unchanged": len(priced) - adv - dec,
            "no_quote": len(rows) - len(priced),
        },  # fmt: skip
    }


async def movers(db: Session, market: MarketDataService, spec: dict) -> dict:
    from marketdesk.services.screener import resolve_universe

    uni = resolve_universe(db, market.source, spec, 500)
    insts = [i for i in uni["instruments"] if (i.kind or "").upper() not in EXCLUDED_KINDS][:MAX_MEMBERS]
    quotes = await market.quotes([i.symbol for i in insts])
    rows = [row_for(i, quotes[i.symbol]) for i in insts]
    currencies = sorted({r["currency"] for r in rows if r.get("currency")})
    return {
        "universe": {"label": uni["label"], "members": len(insts)},
        **rank(rows),
        "rows": rows,
        "currencies": currencies,
        "notes": [
            "Change is against the provider's previous close; traded value is last price × session volume "
            "(partial while a session is open) and is compared only within one currency.",
            "Unusual volume compares the latest completed session with the median of the 20 completed sessions "
            "before it (shown at 1.5× or more).",
        ],
    }

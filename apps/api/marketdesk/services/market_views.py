"""Shape provider results into API payloads with explicit freshness metadata."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.models import Instrument
from marketdesk.providers.base import HISTORY_RANGES, QuoteSnapshot
from marketdesk.services.instruments import instrument_dict
from marketdesk.services.market import MarketDataService, Result

SPARKLINE_POINTS = 66


def quote_dict(q: QuoteSnapshot) -> dict:
    return {
        "last_price": q.last_price,
        "previous_close": q.previous_close,
        "change": q.change,
        "change_percent": q.change_percent,
        "day_high": q.day_high,
        "day_low": q.day_low,
        "volume": q.volume,
        "volume_note": q.volume_note,
        "session_date": q.session_date,
        "market_time": q.market_time,
    }


def snapshot_dict(symbol: str, result: Result[QuoteSnapshot], inst: Instrument | None) -> dict:
    q = result.value
    instrument = instrument_dict(inst, q.instrument if q else None, symbol)
    if q is not None:
        # Provider metadata wins for display where the stored record lacks it.
        for k, v in q.instrument.to_dict().items():
            if v and not instrument.get(k):
                instrument[k] = v
    return {
        "symbol": symbol,
        "instrument": instrument,
        "quote": quote_dict(q) if q else None,
        "sparkline": [
            {"date": b.session_date, "close": b.close} for b in (q.recent_bars[-SPARKLINE_POINTS:] if q else [])
        ],
        "meta": result.meta.to_dict(),
    }


async def build_snapshots(db: Session, market: MarketDataService, symbols: list[str]) -> list[dict]:
    results = await market.quotes(symbols)
    insts = {
        i.symbol: i
        for i in db.scalars(
            select(Instrument).where(Instrument.provider == market.source, Instrument.symbol.in_(list(results)))
        )
    }
    changed = False
    for sym, r in results.items():
        inst = insts.get(sym)
        if inst is not None and r.value is not None:
            ref = r.value.instrument
            for attr in ("name", "exchange", "currency", "timezone", "kind"):
                v = getattr(ref, attr)
                if v and getattr(inst, attr) != v:
                    setattr(inst, attr, v)
                    changed = True
    if changed:
        db.commit()
    return [snapshot_dict(sym, results[sym], insts.get(sym)) for sym in symbols if sym in results]


async def history_payload(market: MarketDataService, symbol: str, range_: str) -> dict:
    result = await market.history(symbol, range_)  # type: ignore[arg-type]
    h = result.value
    return {
        "symbol": symbol,
        "range": range_,
        "adjustment": h.adjustment if h else None,
        "bars": [
            {"time": b.session_date, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
            for b in (h.bars if h else [])
        ],
        "meta": result.meta.to_dict(),
        "supported_ranges": list(HISTORY_RANGES),
    }


async def fundamentals_payload(market: MarketDataService, symbol: str) -> dict:
    result = await market.fundamentals(symbol)
    f = result.value
    values = None
    if f is not None:
        values = {
            "market_cap": f.market_cap,
            "pe_ratio": f.pe_ratio,
            "dividend_yield_percent": f.dividend_yield_percent,
            "fifty_two_week_high": f.fifty_two_week_high,
            "fifty_two_week_low": f.fifty_two_week_low,
            "price_to_book": f.price_to_book,
            "sector": f.sector,
            "industry": f.industry,
            "last_fiscal_year_end": f.last_fiscal_year_end,
            "most_recent_quarter": f.most_recent_quarter,
            "notes": f.notes,
        }
    return {
        "symbol": symbol,
        "currency": f.instrument.currency if f else None,
        "values": values,
        "meta": result.meta.to_dict(),
    }


async def actions_payload(market: MarketDataService, symbol: str) -> dict:
    result = await market.actions(symbol)
    return {
        "symbol": symbol,
        "actions": [
            {"date": a.action_date, "kind": a.kind, "value": a.value, "description": a.description}
            for a in (result.value or [])
        ],
        "meta": result.meta.to_dict(),
    }

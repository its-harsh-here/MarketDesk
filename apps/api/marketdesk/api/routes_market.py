from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, settings_dep
from marketdesk.api.errors import AppError
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.models import Instrument
from marketdesk.schemas import (
    ActionsOut,
    CompareOut,
    FundamentalsOut,
    HistoryOut,
    IntradayOut,
    MarketSessionOut,
    SearchResultOut,
    SnapshotOut,
)
from marketdesk.services.compare import MAX_COMPARE, compare_payload
from marketdesk.services.instruments import validate_symbol
from marketdesk.services.market import MarketDataService
from marketdesk.services.market_views import (
    actions_payload,
    build_snapshots,
    fundamentals_payload,
    history_payload,
    intraday_payload,
)
from marketdesk.services.sessions import market_sessions

router = APIRouter(prefix="/api/market", tags=["market"], dependencies=[Depends(require_reader)])


def benchmark_symbols(settings: Settings, market: MarketDataService) -> list[str]:
    if market.source == "fixture":
        return list(market.provider.dataset.benchmarks)
    cfg = json.loads((settings.starter_config_dir / "starter_watchlist.yahoo.json").read_text())
    return list(cfg.get("benchmarks") or ["^NSEI"])


@router.get("/search", response_model=SearchResultOut)
@off_event_loop
async def search(
    q: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=10, ge=1, le=20),
    region: Literal["all", "IN", "US"] = Query(default="all"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    # The provider's result set is cached per query; the region filter is applied afterwards, so asking for more
    # results upstream keeps a filtered list from coming back nearly empty.
    result = await market.search(q, 20 if region != "all" else limit)
    refs = [r for r in (result.value or []) if region == "all" or r.country == region][:limit]
    known = (
        {
            i.symbol: i
            for i in db.scalars(
                select(Instrument).where(
                    Instrument.provider == market.source, Instrument.symbol.in_([r.symbol for r in refs])
                )
            )
        }
        if refs
        else {}
    )
    out = []
    for r in refs:
        d = {**r.to_dict(), "identity_verified": False}
        inst = known.get(r.symbol)
        if inst is not None:
            for k in ("currency", "timezone", "exchange", "name", "kind", "exchange_code", "mic", "country"):
                d[k] = d.get(k) or getattr(inst, k)
            d["identity_verified"] = inst.identity_verified_at is not None
        out.append(d)
    return {"results": out, "meta": result.meta.to_dict()}


@router.get("/snapshots", response_model=list[SnapshotOut])
@off_event_loop
async def snapshots(
    symbols: str = Query(min_length=1, max_length=2000),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    market: MarketDataService = Depends(market_dep),
):
    raw = [s for s in symbols.split(",") if s.strip()]
    if len(raw) > settings.max_symbols_per_request:
        raise AppError(422, "too_many_symbols", f"Request at most {settings.max_symbols_per_request} symbols.")
    syms = list(dict.fromkeys(validate_symbol(market, s) for s in raw))
    return await build_snapshots(db, market, syms)


@router.get("/benchmarks", response_model=list[SnapshotOut])
@off_event_loop
async def benchmarks(
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    market: MarketDataService = Depends(market_dep),
):
    return await build_snapshots(db, market, benchmark_symbols(settings, market))


@router.get("/history", response_model=HistoryOut)
async def history(
    symbol: str = Query(min_length=1, max_length=32),
    range: Literal["1M", "3M", "6M", "1Y", "5Y"] = Query(default="6M"),  # noqa: A002
    market: MarketDataService = Depends(market_dep),
):
    return await history_payload(market, validate_symbol(market, symbol), range)


@router.get("/intraday", response_model=IntradayOut)
async def intraday(
    symbol: str = Query(min_length=1, max_length=32),
    range: Literal["1D", "5D"] = Query(default="1D"),  # noqa: A002
    market: MarketDataService = Depends(market_dep),
):
    """Regular-session intraday bars: 1D in 5-minute bars, 5D in 15-minute bars (unadjusted)."""
    return await intraday_payload(market, validate_symbol(market, symbol), range)


_SESSIONS: dict = {"at": 0.0, "value": None}


@router.get("/sessions", response_model=list[MarketSessionOut])
async def sessions():
    """Exchange session states for the supported markets (published calendars, not a live exchange feed).

    Answered on the event loop from a 30-second memo, so this call on every page never waits behind slow requests
    for a worker thread (docs/PERFORMANCE_ROADMAP.md 3.5)."""
    now = time.monotonic()
    if _SESSIONS["value"] is None or now - _SESSIONS["at"] > 30:
        _SESSIONS["value"], _SESSIONS["at"] = market_sessions(), now
    return _SESSIONS["value"]


@router.get("/compare", response_model=CompareOut)
async def compare(
    symbols: str = Query(min_length=1, max_length=120),
    range: Literal["1M", "3M", "6M", "1Y", "5Y"] = Query(default="1Y"),  # noqa: A002
    market: MarketDataService = Depends(market_dep),
):
    syms = list(dict.fromkeys(validate_symbol(market, s) for s in symbols.split(",") if s.strip()))
    if not 2 <= len(syms) <= MAX_COMPARE:
        raise AppError(422, "validation_error", f"Compare between 2 and {MAX_COMPARE} different instruments.")
    return await compare_payload(market, syms, range)


@router.get("/fundamentals", response_model=FundamentalsOut)
async def fundamentals(
    symbol: str = Query(min_length=1, max_length=32), market: MarketDataService = Depends(market_dep)
):
    return await fundamentals_payload(market, validate_symbol(market, symbol))


@router.get("/actions", response_model=ActionsOut)
async def actions(symbol: str = Query(min_length=1, max_length=32), market: MarketDataService = Depends(market_dep)):
    return await actions_payload(market, validate_symbol(market, symbol))

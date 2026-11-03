from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, settings_dep
from marketdesk.api.errors import AppError
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.models import Instrument
from marketdesk.schemas import (
    ActionsOut,
    FundamentalsOut,
    HistoryOut,
    SearchResultOut,
    SnapshotOut,
)
from marketdesk.services.instruments import validate_symbol
from marketdesk.services.market import MarketDataService
from marketdesk.services.market_views import (
    actions_payload,
    build_snapshots,
    fundamentals_payload,
    history_payload,
)

router = APIRouter(prefix="/api/market", tags=["market"], dependencies=[Depends(require_reader)])


def benchmark_symbols(settings: Settings, market: MarketDataService) -> list[str]:
    if market.source == "fixture":
        return list(market.provider.dataset.benchmarks)
    return ["^NSEI", "^BSESN", "^NSEBANK"]


@router.get("/search", response_model=SearchResultOut)
async def search(
    q: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    result = await market.search(q, limit)
    refs = result.value or []
    known = {
        i.symbol: i
        for i in db.scalars(
            select(Instrument).where(Instrument.provider == market.source,
                                     Instrument.symbol.in_([r.symbol for r in refs]))
        )
    } if refs else {}
    out = []
    for r in refs:
        d = r.to_dict()
        inst = known.get(r.symbol)
        if inst is not None:
            for k in ("currency", "timezone", "exchange", "name", "kind"):
                d[k] = d.get(k) or getattr(inst, k)
        out.append(d)
    return {"results": out, "meta": result.meta.to_dict()}


@router.get("/snapshots", response_model=list[SnapshotOut])
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


@router.get("/fundamentals", response_model=FundamentalsOut)
async def fundamentals(symbol: str = Query(min_length=1, max_length=32), market: MarketDataService = Depends(market_dep)):
    return await fundamentals_payload(market, validate_symbol(market, symbol))


@router.get("/actions", response_model=ActionsOut)
async def actions(symbol: str = Query(min_length=1, max_length=32), market: MarketDataService = Depends(market_dep)):
    return await actions_payload(market, validate_symbol(market, symbol))

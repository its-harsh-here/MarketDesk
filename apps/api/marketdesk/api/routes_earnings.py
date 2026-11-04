"""Earnings and filing analysis (M07): calendar, period changes, risk-factor changes, guidance quotes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader
from marketdesk.asyncbridge import off_event_loop
from marketdesk.db import get_db
from marketdesk.services import earnings as svc
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/earnings", tags=["earnings"], dependencies=[Depends(require_reader)])


@router.get("/calendar")
@off_event_loop
async def calendar(request: Request, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return await svc.universe_calendar(db, market, request.app.state.research)


@router.get("/{symbol}")
@off_event_loop
async def summary(
    symbol: str, request: Request, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)
):
    inst = await resolve_instrument(db, market, symbol)
    research = request.app.state.research
    return {
        "symbol": inst.symbol,
        "calendar": await svc.calendar_for(db, market, research, inst),
        "changes": await svc.period_changes(db, market, research, inst),
    }


@router.get("/{symbol}/filing-changes")
@off_event_loop
async def filing_changes(
    symbol: str,
    request: Request,
    form: Literal["10-K", "10-Q", "20-F"] = Query(default="10-K"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    inst = await resolve_instrument(db, market, symbol)
    return await svc.filing_changes(db, request.app.state.research, inst, form)


@router.get("/{symbol}/guidance")
@off_event_loop
async def guidance(
    symbol: str, request: Request, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)
):
    inst = await resolve_instrument(db, market, symbol)
    return await svc.guidance(db, request.app.state.research, inst)

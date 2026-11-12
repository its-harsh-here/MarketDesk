"""Company research endpoints (SEC profile, filings, filing events, normalized statements)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader
from marketdesk.asyncbridge import off_event_loop
from marketdesk.db import get_db
from marketdesk.schemas import Model
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService
from marketdesk.services.research import ResearchService

router = APIRouter(prefix="/api/research", tags=["research"], dependencies=[Depends(require_reader)])


class ResearchOut(Model):
    symbol: str
    source: str
    status: str  # available | cached | stale | not_configured | not_applicable | missing | unavailable
    reason: str | None = None
    cik: int | None = None
    fetched_at: str | None = None
    checks: dict[str, Any] | None = None
    data: Any = None


def research_dep(request: Request) -> ResearchService:
    return request.app.state.research


async def _inst(db: Session, market: MarketDataService, symbol: str):
    return await resolve_instrument(db, market, symbol)


@router.get("/profile", response_model=ResearchOut)
@off_event_loop
async def profile(
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    research: ResearchService = Depends(research_dep),
):
    return research.profile(db, await _inst(db, market, symbol))


@router.get("/filings", response_model=ResearchOut)
@off_event_loop
async def filings(
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    research: ResearchService = Depends(research_dep),
):
    return research.filings(db, await _inst(db, market, symbol))


@router.get("/events", response_model=ResearchOut)
@off_event_loop
async def events(
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    research: ResearchService = Depends(research_dep),
):
    return research.events(db, await _inst(db, market, symbol))


@router.get("/segments", response_model=ResearchOut)
@off_event_loop
async def segments(
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    research: ResearchService = Depends(research_dep),
):
    """Revenue (and operating income where tagged) by segment, product and geography from the latest annual
    report's XBRL data (US filers)."""
    return research.segments(db, await _inst(db, market, symbol))


@router.get("/financials", response_model=ResearchOut)
@off_event_loop
async def financials(
    symbol: str = Query(min_length=1, max_length=32),
    period: Literal["annual", "quarterly"] = Query(default="annual"),
    periods: int | None = Query(default=None, ge=2, le=12, description="Columns (default 5 annual, 8 quarterly)"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    research: ResearchService = Depends(research_dep),
):
    inst = await _inst(db, market, symbol)
    quote = await market.quote(inst.symbol)
    q = quote.value
    price = {
        "price": q.last_price if q else None,
        "price_date": q.session_date if q else None,
        "price_ccy": q.instrument.currency if q else None,
    }
    if inst.country != "US":  # outside SEC coverage: the provider's full statements, labelled unofficial
        from marketdesk.services.financial_view import provider_statements

        return await provider_statements(market, inst, period, periods, **price)
    return research.financials(db, inst, period, max_periods=periods, **price)

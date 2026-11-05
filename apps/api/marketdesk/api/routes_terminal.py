"""Terminal views (terminal roadmap): one security, every domain, each figure with its source and date."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, settings_dep
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.services import description
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/terminal", tags=["terminal"], dependencies=[Depends(require_reader)])


@router.get("/description")
@off_event_loop
async def describe(
    request: Request,
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    """Identity, business summary, key statistics and a coverage list for one listing (T1)."""
    inst = await resolve_instrument(db, market, symbol)
    analyst = request.app.state.analyst
    return await description.describe(db, market, request.app.state.research, settings, inst, analyst.enabled)

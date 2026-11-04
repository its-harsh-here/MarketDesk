from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer
from marketdesk.asyncbridge import off_event_loop
from marketdesk.db import get_db
from marketdesk.schemas import (
    JournalCompareOut,
    JournalDetailOut,
    JournalIn,
    JournalOut,
    JournalPage,
    JournalReviewIn,
    JournalReviewOut,
)
from marketdesk.services import journal as svc
from marketdesk.services.clock import today_local
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("", response_model=JournalPage, dependencies=[Depends(require_reader)])
def list_entries(
    symbol: str | None = Query(default=None, max_length=32),
    tag: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=80),
    due: bool = Query(default=False, description="Only entries whose review date has arrived (the review queue)"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_entries(db, today_local(db), symbol, tag, q, limit, offset, due)


def _research(request: Request):
    return request.app.state.research


@router.get("/{eid}", response_model=JournalDetailOut, dependencies=[Depends(require_reader)])
def detail(eid: int, db: Session = Depends(get_db)):
    """The entry with every immutable version (and its evidence) and the review history."""
    return svc.detail(db, eid, today_local(db))


@router.get("/{eid}/compare", response_model=JournalCompareOut, dependencies=[Depends(require_reader)])
@off_event_loop
async def compare(
    eid: int,
    request: Request,
    version: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    """A version's stored evidence beside today's data (fetched now, never stored over the snapshot)."""
    return await svc.compare(db, market, eid, version, _research(request))


@router.post("/{eid}/reviews", response_model=JournalReviewOut, status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def review(
    eid: int,
    body: JournalReviewIn,
    request: Request,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    r = await svc.add_review(db, market, eid, body.model_dump(), today_local(db), _research(request))
    return svc._review_dict(r)


@router.post("", response_model=JournalOut, status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def create(
    body: JournalIn,
    request: Request,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    e = await svc.create_entry(db, market, body.model_dump(), _research(request))
    return svc.entry_dict(e, today_local(db))


@router.put("/{eid}", response_model=JournalOut, dependencies=[Depends(require_writer)])
@off_event_loop
async def update(
    eid: int,
    body: JournalIn,
    request: Request,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    e = await svc.update_entry(db, market, eid, body.model_dump(), _research(request))
    return svc.entry_dict(e, today_local(db))


@router.delete("/{eid}", status_code=204, dependencies=[Depends(require_writer)])
def delete(eid: int, db: Session = Depends(get_db)):
    svc.delete_entry(db, eid)
    return Response(status_code=204)

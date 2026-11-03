from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer
from marketdesk.db import get_db
from marketdesk.schemas import JournalIn, JournalOut, JournalPage
from marketdesk.services import journal as svc
from marketdesk.services.clock import today_local
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("", response_model=JournalPage, dependencies=[Depends(require_reader)])
def list_entries(
    symbol: str | None = Query(default=None, max_length=32),
    tag: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_entries(db, today_local(db), symbol, tag, q, limit, offset)


@router.post("", response_model=JournalOut, status_code=201, dependencies=[Depends(require_writer)])
async def create(body: JournalIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return svc.entry_dict(await svc.create_entry(db, market, body.model_dump()), today_local(db))


@router.put("/{eid}", response_model=JournalOut, dependencies=[Depends(require_writer)])
async def update(
    eid: int, body: JournalIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)
):
    return svc.entry_dict(await svc.update_entry(db, market, eid, body.model_dump()), today_local(db))


@router.delete("/{eid}", status_code=204, dependencies=[Depends(require_writer)])
def delete(eid: int, db: Session = Depends(get_db)):
    svc.delete_entry(db, eid)
    return Response(status_code=204)

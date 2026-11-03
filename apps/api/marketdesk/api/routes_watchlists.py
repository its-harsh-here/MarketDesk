from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer, settings_dep
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.schemas import AddSymbolIn, MembershipOut, ReorderIn, WatchlistIn, WatchlistOut, WatchlistPatch
from marketdesk.services import watchlists as svc
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


@router.get("", response_model=list[WatchlistOut], dependencies=[Depends(require_reader)])
def list_all(db: Session = Depends(get_db)):
    return [svc.watchlist_dict(w) for w in svc.list_watchlists(db)]


@router.get("/membership", response_model=MembershipOut, dependencies=[Depends(require_reader)])
def membership(
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    ids = svc.membership(db, market, symbol)
    return {"symbol": market.validate_symbol(symbol), "watchlist_ids": ids}


@router.post("", response_model=WatchlistOut, status_code=201, dependencies=[Depends(require_writer)])
def create(body: WatchlistIn, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    return svc.watchlist_dict(svc.create_watchlist(db, settings, body.name))


@router.get("/{wid}", response_model=WatchlistOut, dependencies=[Depends(require_reader)])
def get_one(wid: int, db: Session = Depends(get_db)):
    return svc.watchlist_dict(svc.get_watchlist(db, wid))


@router.patch("/{wid}", response_model=WatchlistOut, dependencies=[Depends(require_writer)])
def patch(wid: int, body: WatchlistPatch, db: Session = Depends(get_db)):
    return svc.watchlist_dict(svc.update_watchlist(db, wid, body.model_dump(exclude_unset=True)))


@router.delete("/{wid}", status_code=204, dependencies=[Depends(require_writer)])
def delete(wid: int, db: Session = Depends(get_db)):
    svc.delete_watchlist(db, wid)
    return Response(status_code=204)


@router.post("/{wid}/items", response_model=WatchlistOut, status_code=201, dependencies=[Depends(require_writer)])
async def add_item(
    wid: int,
    body: AddSymbolIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    market: MarketDataService = Depends(market_dep),
):
    return svc.watchlist_dict(await svc.add_symbol(db, settings, market, wid, body.symbol))


@router.delete("/{wid}/items", response_model=WatchlistOut, dependencies=[Depends(require_writer)])
def remove_item(
    wid: int,
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    return svc.watchlist_dict(svc.remove_symbol(db, market, wid, symbol))


@router.put("/{wid}/order", response_model=WatchlistOut, dependencies=[Depends(require_writer)])
def reorder(wid: int, body: ReorderIn, db: Session = Depends(get_db)):
    return svc.watchlist_dict(svc.reorder(db, wid, body.symbols))

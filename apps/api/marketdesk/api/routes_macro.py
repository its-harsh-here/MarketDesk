"""Macro and sector context (M12): watchboard, briefing, sector-relative view, owner-entered exposure links."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer, settings_dep
from marketdesk.api.errors import AppError
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.models import Instrument, MacroLink
from marketdesk.schemas import Model
from marketdesk.services import macro as svc
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService
from marketdesk.services.screener import resolve_universe

router = APIRouter(prefix="/api/macro", tags=["macro"])


class LinkIn(Model):
    symbol: str = Field(min_length=1, max_length=32)
    series_symbol: str = Field(min_length=1, max_length=32)
    relation: Literal["cost", "revenue", "rates", "fx", "demand", "other"]
    direction: Literal["up_helps", "up_hurts", "unclear"]
    note: str = Field(default="", max_length=1000)


def _links(db: Session) -> list[dict]:
    rows = db.scalars(select(MacroLink).order_by(MacroLink.id))
    out = []
    for lk in rows:
        inst = db.get(Instrument, lk.instrument_id)
        if inst is not None:
            out.append(svc.link_dict(lk, inst))
    return out


@router.get("/watchboard", dependencies=[Depends(require_reader)])
@off_event_loop
async def watchboard(
    window: Literal["1w", "1m", "3m", "1y"] = Query(default="1w"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    board = await svc.watchboard(market)
    return {**board, "briefing": svc.briefing(board, _links(db), window)}


@router.get("/sector-relative", dependencies=[Depends(require_reader)])
@off_event_loop
async def sector_relative(
    kind: Literal["watchlists", "watchlist", "holdings", "list"] = Query(default="watchlists"),
    id: int | None = Query(default=None),
    metric: str = Query(default="return_3m_pct", max_length=20),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    uni = resolve_universe(
        db, market.source, {"kind": kind, **({"id": id} if id is not None else {})}, settings.screener_max_universe
    )
    board = await svc.watchboard(market)
    if metric not in ("return_1m_pct", "return_3m_pct", "return_1y_pct"):
        raise AppError(422, "bad_metric", "Choose the 1-month, 3-month or 1-year return.")
    out = svc.sector_relative(db, market.source, uni["instruments"], metric, svc.benchmark_returns(board, metric))
    return {**out, "universe": {k: v for k, v in uni.items() if k != "instruments"}}


@router.get("/links", dependencies=[Depends(require_reader)])
@off_event_loop
async def links(
    with_correlation: bool = Query(default=False),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    rows = _links(db)
    if with_correlation:
        for r in rows:
            inst = db.scalar(
                select(Instrument).where(Instrument.symbol == r["symbol"], Instrument.provider == market.source)
            )
            r["correlation"] = await svc.link_correlation(market, inst, r["series_symbol"]) if inst else None
    return {
        "links": rows,
        "series": [s.__dict__ for s in svc.series_list(market)],
        "note": "Links are your own entries. The correlation of returns is descriptive (one year; daily within one "
        "exchange time zone, weekly across) and is not evidence of cause.",
    }


@router.post("/links", status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def add_link(body: LinkIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    inst = await resolve_instrument(db, market, body.symbol)
    if body.series_symbol not in {s.symbol for s in svc.series_list(market)}:
        raise AppError(422, "unknown_series", "Choose one of the watchboard series.")
    lk = MacroLink(
        instrument_id=inst.id,
        series_symbol=body.series_symbol,
        relation=body.relation,
        direction=body.direction,
        note=body.note.strip(),
    )
    db.add(lk)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise AppError(409, "duplicate_link", f"{inst.symbol} is already linked to {body.series_symbol}.") from err
    return svc.link_dict(lk, inst)


@router.delete("/links/{lid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_link(lid: int, db: Session = Depends(get_db)):
    lk = db.get(MacroLink, lid)
    if lk is None:
        raise AppError(404, "not_found", "That link no longer exists.")
    db.delete(lk)
    db.commit()
    return Response(status_code=204)

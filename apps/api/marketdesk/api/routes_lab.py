"""Research lab (M13): reproducible rule tests and an isolated paper portfolio. Everything is simulated."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer, settings_dep
from marketdesk.api.errors import AppError
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.models import PaperOrder, PaperPortfolio, ResearchRun
from marketdesk.schemas import Model
from marketdesk.services import research_lab as svc
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/lab", tags=["lab"])


class RunIn(Model):
    symbol: str = Field(min_length=1, max_length=32)
    rule: Literal["buy_and_hold", "sma_cross", "momentum"]
    params: dict[str, Any] = Field(default_factory=dict)
    fee_pct: Decimal = Field(default=Decimal("0.1"), ge=0, le=2)
    slippage_bps: Decimal = Field(default=Decimal(5), ge=0, le=200)
    starting_cash: Decimal = Field(default=Decimal(100000), ge=1000, le=Decimal("1e12"))
    benchmark: str | None = Field(default=None, max_length=32)


class PaperIn(Model):
    name: str = Field(min_length=1, max_length=60)
    currency: Literal["INR", "USD"] = "INR"
    starting_cash: Decimal = Field(default=Decimal(100000), ge=1000, le=Decimal("1e12"))
    fee_pct: Decimal = Field(default=Decimal("0.1"), ge=0, le=2)
    slippage_bps: Decimal = Field(default=Decimal(5), ge=0, le=200)


class OrderIn(Model):
    side: Literal["BUY", "SELL"]
    symbol: str = Field(min_length=1, max_length=32)
    quantity: Decimal = Field(gt=0, le=Decimal("1e9"))


@router.get("/review", dependencies=[Depends(require_reader)])
def review():
    return {"items": svc.REVIEW, "label": svc.SIMULATED}


@router.get("/runs", dependencies=[Depends(require_reader)])
def runs(db: Session = Depends(get_db)):
    rows = db.scalars(select(ResearchRun).order_by(ResearchRun.id.desc()).limit(50))
    return [svc.run_dict(r, full=False) for r in rows]


@router.post("/runs", status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def create_run(
    body: RunIn,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    return svc.run_dict(await svc.run_test(db, market, settings, body.model_dump()))


@router.get("/runs/{rid}", dependencies=[Depends(require_reader)])
def get_run(rid: int, db: Session = Depends(get_db)):
    r = db.get(ResearchRun, rid)
    if r is None:
        raise AppError(404, "not_found", "That run no longer exists.")
    return svc.run_dict(r)


@router.post("/runs/{rid}/reproduce", dependencies=[Depends(require_reader)])
@off_event_loop
async def reproduce(rid: int, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    r = db.get(ResearchRun, rid)
    if r is None:
        raise AppError(404, "not_found", "That run no longer exists.")
    return await svc.reproduce(db, market, r)


@router.delete("/runs/{rid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_run(rid: int, db: Session = Depends(get_db)):
    r = db.get(ResearchRun, rid)
    if r is None:
        raise AppError(404, "not_found", "That run no longer exists.")
    db.delete(r)
    db.commit()
    return Response(status_code=204)


@router.get("/paper", dependencies=[Depends(require_reader)])
def list_paper(db: Session = Depends(get_db)):
    return [
        {"id": p.id, "name": p.name, "currency": p.currency}
        for p in db.scalars(select(PaperPortfolio).order_by(PaperPortfolio.id))
    ]


@router.post("/paper", status_code=201, dependencies=[Depends(require_writer)])
def create_paper(body: PaperIn, db: Session = Depends(get_db)):
    pf = PaperPortfolio(
        name=" ".join(body.name.split()),
        currency=body.currency,
        starting_cash=body.starting_cash,
        fee_pct=body.fee_pct,
        slippage_bps=body.slippage_bps,
    )
    db.add(pf)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise AppError(409, "duplicate_name", f"A paper portfolio named {pf.name!r} already exists.") from err
    return {"id": pf.id, "name": pf.name, "currency": pf.currency}


def _pf(db: Session, pid: int) -> PaperPortfolio:
    pf = db.get(PaperPortfolio, pid)
    if pf is None:
        raise AppError(404, "not_found", "That paper portfolio no longer exists.")
    return pf


@router.get("/paper/{pid}", dependencies=[Depends(require_reader)])
@off_event_loop
async def paper(pid: int, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return await svc.paper_state(db, market, _pf(db, pid))


@router.post("/paper/{pid}/orders", status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def order(
    pid: int, body: OrderIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)
):
    pf = _pf(db, pid)
    await svc.place_order(db, market, pf, body.side, body.symbol, body.quantity)
    db.refresh(pf)
    return await svc.paper_state(db, market, pf)


@router.delete("/paper/{pid}/orders/{oid}", dependencies=[Depends(require_writer)])
@off_event_loop
async def cancel(pid: int, oid: int, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    pf = _pf(db, pid)
    o = db.get(PaperOrder, oid)
    if o is None or o.portfolio_id != pid:
        raise AppError(404, "not_found", "That order no longer exists.")
    state = await svc.paper_state(db, market, pf)
    if next((x for x in state["orders"] if x["id"] == oid), {}).get("status") != "pending":
        raise AppError(409, "not_pending", "Only orders still waiting for a fill can be cancelled.")
    db.delete(o)
    db.commit()
    db.refresh(pf)
    return await svc.paper_state(db, market, pf)


@router.delete("/paper/{pid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_paper(pid: int, db: Session = Depends(get_db)):
    db.delete(_pf(db, pid))
    db.commit()
    return Response(status_code=204)

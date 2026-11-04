"""Valuation lab (M11): DCF inputs and runs, peer-multiple ranges, saved scenarios, portfolio stress tests."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer
from marketdesk.api.errors import AppError
from marketdesk.asyncbridge import off_event_loop
from marketdesk.db import get_db
from marketdesk.models import ValuationScenario
from marketdesk.schemas import Model
from marketdesk.services import valuation as svc
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService

router = APIRouter(tags=["valuation"])
Axis = Literal["discount_pct", "terminal_growth_pct", "growth_pct"]


class DcfIn(Model):
    inputs: dict[str, Any]
    rows_axis: Axis = "discount_pct"
    cols_axis: Axis = "terminal_growth_pct"


class ScenarioIn(Model):
    name: str = Field(min_length=1, max_length=40)
    case: Literal["bear", "base", "bull", "custom"] = "custom"
    inputs: dict[str, Any]
    notes: str = Field(default="", max_length=4000)


class StressIn(Model):
    account: Literal["INR", "USD", "ALL"] = "ALL"
    market_shocks: dict[str, Decimal] = Field(default_factory=dict, max_length=10)
    symbol_shocks: dict[str, Decimal] = Field(default_factory=dict, max_length=60)
    fx_shocks: dict[str, Decimal] = Field(default_factory=dict, max_length=5)


@router.get("/api/valuation/{symbol}/inputs", dependencies=[Depends(require_reader)])
@off_event_loop
async def inputs(symbol: str, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return await svc.inputs(db, market, symbol)


@router.post("/api/valuation/{symbol}/dcf", dependencies=[Depends(require_reader)])
@off_event_loop
async def dcf(symbol: str, body: DcfIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    info = await svc.inputs(db, market, symbol)
    if not info["dcf_applicable"]:
        raise AppError(422, "dcf_not_applicable", info["dcf_reason"])
    price = Decimal(info["price"]) if info["price"] else None
    return {
        "symbol": info["symbol"],
        "currency": info["currency"],
        "price": info["price"],
        **svc.run_dcf(body.inputs, price, body.rows_axis, body.cols_axis),
    }


@router.get("/api/valuation/{symbol}/multiples", dependencies=[Depends(require_reader)])
@off_event_loop
async def multiples(symbol: str, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return await svc.multiples(db, market, symbol)


@router.get("/api/valuation/{symbol}/scenarios", dependencies=[Depends(require_reader)])
@off_event_loop
async def list_scenarios(symbol: str, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    inst = await resolve_instrument(db, market, symbol)
    rows = db.scalars(
        select(ValuationScenario).where(ValuationScenario.instrument_id == inst.id).order_by(ValuationScenario.id)
    )
    return [svc.scenario_dict(s) for s in rows]


@router.post("/api/valuation/{symbol}/scenarios", status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def create_scenario(
    symbol: str, body: ScenarioIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)
):
    inst = await resolve_instrument(db, market, symbol)
    s = ValuationScenario(
        instrument_id=inst.id,
        name=" ".join(body.name.split()),
        case=body.case,
        inputs=svc.clean_inputs(body.inputs),
        notes=body.notes,
    )
    db.add(s)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise AppError(409, "duplicate_name", f"A scenario named {s.name!r} already exists for {inst.symbol}.") from err
    return svc.scenario_dict(s)


@router.put("/api/valuation/scenarios/{sid}", dependencies=[Depends(require_writer)])
def update_scenario(sid: int, body: ScenarioIn, db: Session = Depends(get_db)):
    s = db.get(ValuationScenario, sid)
    if s is None:
        raise AppError(404, "not_found", "That scenario no longer exists.")
    s.name, s.case, s.inputs, s.notes = (
        " ".join(body.name.split()),
        body.case,
        svc.clean_inputs(body.inputs),
        body.notes,
    )
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise AppError(409, "duplicate_name", "Another scenario for this instrument has that name.") from err
    return svc.scenario_dict(s)


@router.delete("/api/valuation/scenarios/{sid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_scenario(sid: int, db: Session = Depends(get_db)):
    s = db.get(ValuationScenario, sid)
    if s is None:
        raise AppError(404, "not_found", "That scenario no longer exists.")
    db.delete(s)
    db.commit()
    return Response(status_code=204)


@router.post("/api/portfolio/stress", dependencies=[Depends(require_reader)])
@off_event_loop
async def stress(body: StressIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return await svc.stress(db, market, body.account, body.market_shocks, body.symbol_shocks, body.fx_shocks)

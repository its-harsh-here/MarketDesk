"""Portfolio performance and risk (M09): returns vs a benchmark, exposure, correlations, targets and simulations."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer, settings_dep
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.schemas import Model
from marketdesk.services import performance as svc
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/portfolio", tags=["performance"])
Account = Literal["INR", "USD", "ALL"]


class TargetIn(Model):
    symbol: str = Field(min_length=1, max_length=32)
    target_pct: Decimal = Field(ge=0, le=100)


class TargetsIn(Model):
    targets: list[TargetIn] = Field(max_length=60)


class RebalanceIn(Model):
    account: Literal["INR", "USD"]
    extra_cash: Decimal = Field(default=Decimal(0), ge=0, le=Decimal("1e12"))
    whole_shares: bool = True
    fee_pct: Decimal = Field(default=Decimal(0), ge=0, le=5)


@router.get("/performance", dependencies=[Depends(require_reader)])
@off_event_loop
async def performance(
    account: Account = Query(default="INR"),
    benchmark: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    return await svc.performance(db, market, settings, account, benchmark)


@router.get("/exposure", dependencies=[Depends(require_reader)])
@off_event_loop
async def exposure(
    account: Account = Query(default="INR"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    return await svc.exposure(db, market, account)


@router.get("/correlations", dependencies=[Depends(require_reader)])
@off_event_loop
async def correlations(
    account: Account = Query(default="INR"),
    benchmark: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    return await svc.correlations(db, market, settings, account, benchmark)


@router.get("/targets", dependencies=[Depends(require_reader)])
def get_targets(account: Literal["INR", "USD"] = Query(default="INR"), db: Session = Depends(get_db)):
    return {"account": account, "targets": svc.get_targets(db, account)}


@router.put("/targets", dependencies=[Depends(require_writer)])
def put_targets(body: TargetsIn, account: Literal["INR", "USD"] = Query(default="INR"), db: Session = Depends(get_db)):
    rows = [t.model_dump() for t in body.targets]
    return {"account": account, "targets": svc.set_targets(db, account, rows)}


@router.post("/rebalance", dependencies=[Depends(require_reader)])
@off_event_loop
async def rebalance(body: RebalanceIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return await svc.simulate(db, market, body.account, body.extra_cash, body.whole_shares, body.fee_pct)

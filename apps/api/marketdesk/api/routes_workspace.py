"""Workspace polish (M14): workspace presets, provider/AI usage with owner quotas, and research exports."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer, settings_dep
from marketdesk.api.errors import AppError
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.models import AppSetting
from marketdesk.schemas import Model, WorkspaceApplied, WorkspaceIn, WorkspaceOut, WorkspacesOut
from marketdesk.services import research_export, workspaces
from marketdesk.services.analyst import QUOTA_KEY
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService
from marketdesk.services.prefs import get_prefs

router = APIRouter(prefix="/api", tags=["workspace"])


# --------------------------------------------------------------------- workspaces
@router.get("/workspaces", response_model=WorkspacesOut, dependencies=[Depends(require_reader)])
def list_workspaces(db: Session = Depends(get_db)):
    return workspaces.listing(db)


class WorkspaceCreate(WorkspaceIn):
    capture: bool = False  # take density, default watchlist and chart symbol from the current preferences


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, dependencies=[Depends(require_writer)])
def create_workspace(body: WorkspaceCreate, db: Session = Depends(get_db)):
    return workspaces.create(db, body.model_dump(exclude={"capture"}), body.capture)


@router.put("/workspaces/{wid}", response_model=WorkspaceOut, dependencies=[Depends(require_writer)])
def replace_workspace(wid: str, body: WorkspaceIn, db: Session = Depends(get_db)):
    return workspaces.replace(db, wid, body.model_dump())


@router.delete("/workspaces/{wid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_workspace(wid: str, db: Session = Depends(get_db)):
    workspaces.delete(db, wid)
    return Response(status_code=204)


@router.post("/workspaces/{wid}/apply", response_model=WorkspaceApplied, dependencies=[Depends(require_writer)])
def apply_workspace(wid: str, db: Session = Depends(get_db)):
    return workspaces.apply(db, wid)


# --------------------------------------------------------------------- usage and quotas
@router.get("/usage", dependencies=[Depends(require_reader)])
def usage(
    request: Request,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    analyst = request.app.state.analyst
    research = request.app.state.research
    ai = analyst.status(db)
    lim = analyst.limits(db)
    return {
        "provider": {
            **market.health(),
            **market.usage(),
            "cache_ttl_seconds": dict(market.ttl),
            "note": "Counts are for this web process since it started; the worker counts its own requests.",
        },
        "sec": {
            "enabled": research.client.enabled,
            "reason": research.client.problem,
            "max_requests_per_second": settings.sec_max_requests_per_second,
        },
        "ai": {
            "enabled": ai["enabled"],
            "reason": ai["reason"],
            "provider_label": ai.get("provider_label"),
            "model": ai.get("model"),
            "budget": ai["budget"],
            "provider_limits": ai.get("provider_limits"),
            "server_caps": {k: str(v) if isinstance(v, Decimal) else v for k, v in lim["server"].items()},
            "owner_quotas": lim["owner"],
            "free_tier": analyst.free_tier,
        },
        "refresh": {
            "quote_refresh_seconds": get_prefs(db)["quote_refresh_seconds"],
            "worker_poll_seconds": settings.alert_poll_seconds,
        },
    }


class QuotasIn(Model):
    requests: int | None = Field(default=None, ge=0, le=10_000)
    tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    usd: Decimal | None = Field(default=None, ge=0, le=1000)


@router.put("/usage/quotas", dependencies=[Depends(require_writer)])
def set_quotas(body: QuotasIn, request: Request, db: Session = Depends(get_db)):
    """The owner's own daily AI limits. Each may only lower the server cap; empty means 'use the server cap'."""
    analyst = request.app.state.analyst
    caps = analyst.limits(db)["server"]
    over = [k for k, v in body.model_dump().items() if v is not None and Decimal(str(v)) > Decimal(str(caps[k]))]
    if over:
        raise AppError(
            422,
            "above_server_cap",
            "A quota can only lower the server's limit: "
            + ", ".join(f"{k} ≤ {caps[k]}" for k in over)
            + ". Raise the server limit in its environment instead.",
        )
    value = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in body.model_dump().items()}
    row = db.get(AppSetting, QUOTA_KEY)
    if row is None:
        db.add(AppSetting(key=QUOTA_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return analyst.limits(db) | {"effective": {k: str(v) for k, v in analyst.limits(db)["effective"].items()}}


# --------------------------------------------------------------------- research export
@router.get("/export/research", dependencies=[Depends(require_reader)])
@off_event_loop
async def export_research(
    request: Request,
    symbol: str = Query(min_length=1, max_length=32),
    include: str = Query(default="ai", max_length=40, description="Comma list of: ai, journal, holdings"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    principal=Depends(require_reader),
):
    wanted = {x.strip() for x in include.split(",") if x.strip()}
    unknown = wanted - set(research_export.SECTIONS)
    if unknown:
        raise AppError(422, "bad_include", f"Unknown section(s): {', '.join(sorted(unknown))}.")
    if principal.read_only and wanted & set(research_export.PRIVATE):
        raise AppError(403, "read_only", "Private sections are not exported from the public demo.")
    inst = await resolve_instrument(db, market, symbol)
    holdings = None
    if "holdings" in wanted:
        from marketdesk.services.portfolio import portfolio_summary

        ccy = inst.currency if inst.currency in ("INR", "USD") else None
        holdings = (await portfolio_summary(db, market, ccy))["holdings"] if ccy else []
    name, text = await research_export.build(db, market, request.app.state.research, inst, wanted, holdings)
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )

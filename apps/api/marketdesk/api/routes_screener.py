"""Screener (M06): universes, screens over the stored snapshot, saved screens, export, heatmap, refresh, peers."""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer, settings_dep
from marketdesk.api.errors import AppError
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import db_session, get_db
from marketdesk.models import PeerSet, SavedScreen, ScreenUniverse
from marketdesk.schemas import Model
from marketdesk.services import screener as svc
from marketdesk.services.fx import valuation_rate
from marketdesk.services.instruments import find_instrument, resolve_instrument
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/screener", tags=["screener"])
MAX_PEERS = 5
_SPLIT = re.compile(r"[\s,;]+")


class UniverseSpec(Model):
    kind: Literal["watchlists", "watchlist", "holdings", "list"]
    id: int | None = None


class ScreenIn(Model):
    universe: UniverseSpec
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    sort: dict[str, str] | None = None


class SavedScreenIn(ScreenIn):
    name: str = Field(min_length=1, max_length=80)


class SavedScreenPatch(Model):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    universe: UniverseSpec | None = None
    filters: list[dict[str, Any]] | None = Field(default=None, max_length=12)
    sort: dict[str, str] | None = None


class ListIn(Model):
    name: str = Field(min_length=1, max_length=60)
    symbols: str = Field(min_length=1, max_length=4000)  # pasted: separated by spaces, commas or new lines


class ListPatch(Model):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    symbols: str | None = Field(default=None, min_length=1, max_length=4000)


class PeersIn(Model):
    symbols: list[str] = Field(max_length=MAX_PEERS)


class RefreshIn(Model):
    universe: UniverseSpec


async def _rates(market: MarketDataService) -> dict:
    fx = await valuation_rate(market, "USD", "INR")
    return {("USD", "INR"): fx.get("rate"), "meta": fx} if fx.get("rate") else {"meta": fx}


def _spec(u: UniverseSpec) -> dict:
    return u.model_dump(exclude_none=True)


@router.get("/catalog", dependencies=[Depends(require_reader)])
def catalog():
    return svc.metric_catalog()


@router.get("/universes", dependencies=[Depends(require_reader)])
def universes(
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    return {"options": svc.universe_options(db, market.source), "max_size": settings.screener_max_universe}


async def _resolve_symbols(
    db: Session, market: MarketDataService, text: str, limit: int
) -> tuple[list[str], list[dict]]:
    raw = [s for s in _SPLIT.split(text.strip()) if s]
    if len(raw) > limit:
        raise AppError(422, "too_many_symbols", f"A list holds at most {limit} symbols; this one has {len(raw)}.")
    ok, skipped = [], []
    for s in dict.fromkeys(x.upper() for x in raw):
        try:
            inst = await resolve_instrument(db, market, s)
        except AppError as err:
            skipped.append({"symbol": s, "reason": err.message})
            continue
        if (inst.kind or "").upper() in svc.EXCLUDED_KINDS:
            skipped.append({"symbol": s, "reason": "Indices and currencies are not screened."})
        elif inst.symbol not in ok:
            ok.append(inst.symbol)
    if not ok:
        raise AppError(422, "no_valid_symbols", "None of the symbols could be verified.", {"skipped": skipped})
    return ok, skipped


def _list_out(ul: ScreenUniverse, skipped: list[dict] | None = None) -> dict:
    return {"id": ul.id, "name": ul.name, "symbols": list(ul.symbols), "skipped": skipped or []}


@router.post("/universes", status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def create_list(
    body: ListIn,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    name = " ".join(body.name.split())
    if db.scalar(select(ScreenUniverse).where(ScreenUniverse.name == name)):
        raise AppError(409, "duplicate_name", f"A list named {name!r} already exists.")
    symbols, skipped = await _resolve_symbols(db, market, body.symbols, settings.screener_max_universe)
    ul = ScreenUniverse(name=name, symbols=symbols)
    db.add(ul)
    db.commit()
    return _list_out(ul, skipped)


@router.patch("/universes/{uid}", dependencies=[Depends(require_writer)])
@off_event_loop
async def update_list(
    uid: int,
    body: ListPatch,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    ul = db.get(ScreenUniverse, uid)
    if ul is None:
        raise AppError(404, "not_found", "That list no longer exists.")
    skipped: list[dict] = []
    if body.name is not None:
        name = " ".join(body.name.split())
        clash = db.scalar(select(ScreenUniverse).where(ScreenUniverse.name == name, ScreenUniverse.id != uid))
        if clash:
            raise AppError(409, "duplicate_name", f"A list named {name!r} already exists.")
        ul.name = name
    if body.symbols is not None:
        ul.symbols, skipped = await _resolve_symbols(db, market, body.symbols, settings.screener_max_universe)
    db.commit()
    return _list_out(ul, skipped)


@router.delete("/universes/{uid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_list(uid: int, db: Session = Depends(get_db)):
    ul = db.get(ScreenUniverse, uid)
    if ul is None:
        raise AppError(404, "not_found", "That list no longer exists.")
    users = [
        s.name
        for s in db.scalars(select(SavedScreen))
        if s.universe.get("kind") == "list" and s.universe.get("id") == uid
    ]
    if users:
        raise AppError(
            409, "list_in_use", f"Saved screens use this list: {', '.join(users)}. Change or delete them first."
        )
    db.delete(ul)
    db.commit()
    return Response(status_code=204)


@router.post("/run", dependencies=[Depends(require_reader)])
@off_event_loop
async def run(
    body: ScreenIn,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    return svc.run_screen(
        db,
        market.source,
        _spec(body.universe),
        body.filters,
        body.sort,
        await _rates(market),
        max_size=settings.screener_max_universe,
        hours=settings.screener_snapshot_hours,
    )


@router.post("/export", dependencies=[Depends(require_reader)])
@off_event_loop
async def export(
    body: ScreenIn,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    result = svc.run_screen(
        db,
        market.source,
        _spec(body.universe),
        body.filters,
        body.sort,
        await _rates(market),
        max_size=settings.screener_max_universe,
        hours=settings.screener_snapshot_hours,
    )
    return Response(
        svc.export_csv(result),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="marketdesk-screen.csv"'},
    )


@router.get("/heatmap", dependencies=[Depends(require_reader)])
@off_event_loop
async def heatmap(
    kind: Literal["watchlists", "watchlist", "holdings", "list"] = Query(default="watchlists"),
    id: int | None = Query(default=None),
    metric: str = Query(default="change_1d_pct", max_length=24),
    weighting: str = Query(default="equal", max_length=12),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    spec = {"kind": kind, **({"id": id} if id is not None else {})}
    return svc.heatmap(
        db,
        market.source,
        spec,
        metric,
        weighting,
        await _rates(market),
        max_size=settings.screener_max_universe,
        hours=settings.screener_snapshot_hours,
    )


@router.get("/refresh", dependencies=[Depends(require_reader)])
def refresh_status():
    return svc.REFRESH_JOB.state


@router.post("/refresh", status_code=202, dependencies=[Depends(require_reader)])
@off_event_loop
async def refresh(
    body: RefreshIn, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)
):
    """Load or update the snapshot of a universe's members (missing or older than the refresh window), bounded."""
    market: MarketDataService = request.app.state.market
    uni = svc.resolve_universe(db, market.source, _spec(body.universe), settings.screener_max_universe)
    ids = [i.id for i in uni["instruments"]]

    async def job(progress):
        from marketdesk.models import Instrument

        with db_session() as s:
            insts = [i for i in (s.get(Instrument, x) for x in ids) if i is not None]
            return await svc.refresh_instruments(
                s,
                market,
                insts,
                hours=settings.screener_snapshot_hours,
                limit=settings.screener_refresh_batch,
                progress=progress,
            )

    if not svc.REFRESH_JOB.start(uni["label"], job):
        raise AppError(429, "busy", "A refresh is already running; wait for it to finish.")
    return svc.REFRESH_JOB.state


# --------------------------------------------------------------------- saved screens
@router.get("/screens", dependencies=[Depends(require_reader)])
def list_screens(db: Session = Depends(get_db)):
    return [svc.screen_dict(s) for s in db.scalars(select(SavedScreen).order_by(SavedScreen.name))]


def _check_screen(db: Session, provider: str, universe: dict, filters: list, max_size: int) -> list[dict]:
    svc.resolve_universe(db, provider, universe, max_size)  # the universe must exist
    return svc.validate_filters(filters)


@router.post("/screens", status_code=201, dependencies=[Depends(require_writer)])
def create_screen(
    body: SavedScreenIn,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    filters = _check_screen(db, market.source, _spec(body.universe), body.filters, settings.screener_max_universe)
    s = SavedScreen(name=" ".join(body.name.split()), universe=_spec(body.universe), filters=filters, sort=body.sort)
    db.add(s)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise AppError(409, "duplicate_name", f"A saved screen named {s.name!r} already exists.") from err
    return svc.screen_dict(s)


@router.patch("/screens/{sid}", dependencies=[Depends(require_writer)])
def update_screen(
    sid: int,
    body: SavedScreenPatch,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    s = db.get(SavedScreen, sid)
    if s is None:
        raise AppError(404, "not_found", "That saved screen no longer exists.")
    universe = _spec(body.universe) if body.universe else s.universe
    filters = body.filters if body.filters is not None else s.filters
    s.filters = _check_screen(db, market.source, universe, filters, settings.screener_max_universe)
    s.universe = universe
    if body.name is not None:
        s.name = " ".join(body.name.split())
    if body.sort is not None:
        s.sort = body.sort
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise AppError(409, "duplicate_name", "A saved screen with that name already exists.") from err
    return svc.screen_dict(s)


@router.delete("/screens/{sid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_screen(sid: int, db: Session = Depends(get_db)):
    s = db.get(SavedScreen, sid)
    if s is None:
        raise AppError(404, "not_found", "That saved screen no longer exists.")
    db.delete(s)
    db.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------- peers
async def _peers_payload(db: Session, market: MarketDataService, settings: Settings, symbol: str) -> dict:
    inst = await resolve_instrument(db, market, symbol)
    hours = settings.screener_snapshot_hours
    await svc.refresh_instruments(db, market, [inst], hours=hours, limit=1)
    rates = await _rates(market)
    ps = db.scalar(select(PeerSet).where(PeerSet.instrument_id == inst.id))
    if ps is not None:
        source = "saved"
        chosen = [{"symbol": s, "reason": "Chosen by you"} for s in ps.peers]
    else:
        source = "suggested"
        chosen = svc.suggest_peers(db, inst, market.source, rates, MAX_PEERS)
    peers = [i for c in chosen if (i := find_instrument(db, market.source, c["symbol"])) is not None]
    await svc.refresh_instruments(db, market, peers, hours=hours, limit=MAX_PEERS)
    return {
        "symbol": inst.symbol,
        "source": source,
        "peers": chosen,
        "rows": svc.peer_table(db, inst, peers, market.source),
        "fx": svc._fx_note(rates) if len({inst.currency, *(p.currency for p in peers)}) > 1 else None,
        "note": (
            "Suggestions come from instruments in your watchlists, holdings, lists and saved peer groups that share "
            "the industry (then the sector), closest in market cap. Edit them to choose your own."
            if source == "suggested"
            else "Peers you chose. Reset to return to suggestions."
        ),
    }


@router.get("/peers/{symbol}", dependencies=[Depends(require_reader)])
@off_event_loop
async def get_peers(
    symbol: str,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    return await _peers_payload(db, market, settings, symbol)


@router.put("/peers/{symbol}", dependencies=[Depends(require_writer)])
@off_event_loop
async def put_peers(
    symbol: str,
    body: PeersIn,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    inst = await resolve_instrument(db, market, symbol)
    chosen: list[str] = []
    for s in body.symbols:
        peer = await resolve_instrument(db, market, s)
        if peer.id == inst.id:
            raise AppError(422, "bad_peer", f"{peer.symbol} cannot be its own peer.")
        if (peer.kind or "").upper() in svc.EXCLUDED_KINDS:
            raise AppError(422, "bad_peer", f"{peer.symbol} is an index or currency, not a company.")
        if peer.symbol not in chosen:
            chosen.append(peer.symbol)
    svc.set_peers(db, inst, chosen)
    return await _peers_payload(db, market, settings, inst.symbol)


@router.delete("/peers/{symbol}", dependencies=[Depends(require_writer)])
@off_event_loop
async def reset_peers(
    symbol: str,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    inst = await resolve_instrument(db, market, symbol)
    ps = db.scalar(select(PeerSet).where(PeerSet.instrument_id == inst.id))
    if ps is not None:
        db.delete(ps)
        db.commit()
    return await _peers_payload(db, market, settings, inst.symbol)

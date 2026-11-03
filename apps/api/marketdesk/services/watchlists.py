"""Watchlist CRUD with bounded sizes and persisted order/sort settings."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.config import Settings
from marketdesk.models import Instrument, Watchlist, WatchlistItem
from marketdesk.services.instruments import instrument_dict, resolve_instrument, validate_symbol
from marketdesk.services.market import MarketDataService
from marketdesk.services.prefs import get_prefs, update_prefs


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise AppError(
            422,
            "validation_error",
            "Name cannot be blank.",
            {"fields": [{"field": "name", "message": "Name cannot be blank."}]},
        )
    return cleaned


def watchlist_dict(w: Watchlist, include_items: bool = True) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "position": w.position,
        "sort_key": w.sort_key,
        "sort_dir": w.sort_dir,
        "item_count": len(w.items),
        "items": [
            {
                "symbol": it.instrument.symbol,
                "instrument": instrument_dict(it.instrument),
                "position": it.position,
                "added_at": it.added_at,
            }
            for it in w.items
        ]
        if include_items
        else [],
        "created_at": w.created_at,
        "updated_at": w.updated_at,
    }


def list_watchlists(db: Session) -> list[Watchlist]:
    return list(db.scalars(select(Watchlist).order_by(Watchlist.position, Watchlist.id)))


def get_watchlist(db: Session, wid: int) -> Watchlist:
    w = db.get(Watchlist, wid)
    if w is None:
        raise AppError(404, "not_found", "Watchlist not found.")
    return w


def create_watchlist(db: Session, settings: Settings, name: str) -> Watchlist:
    count = db.scalar(select(func.count()).select_from(Watchlist)) or 0
    if count >= settings.max_watchlists:
        raise AppError(409, "limit_reached", f"You can keep up to {settings.max_watchlists} watchlists.")
    pos = (db.scalar(select(func.max(Watchlist.position))) or 0) + 1
    w = Watchlist(name=_clean_name(name), position=pos)
    db.add(w)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "duplicate_name", "A watchlist with this name already exists.") from exc
    if get_prefs(db)["default_watchlist_id"] is None:
        update_prefs(db, {"default_watchlist_id": w.id})
    return w


def update_watchlist(db: Session, wid: int, patch: dict) -> Watchlist:
    w = get_watchlist(db, wid)
    if patch.get("name") is not None:
        w.name = _clean_name(patch["name"])
    if patch.get("sort_key") is not None:
        w.sort_key = patch["sort_key"]
    if patch.get("sort_dir") is not None:
        w.sort_dir = patch["sort_dir"]
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "duplicate_name", "A watchlist with this name already exists.") from exc
    return w


def delete_watchlist(db: Session, wid: int) -> None:
    w = get_watchlist(db, wid)
    db.delete(w)
    db.commit()
    prefs = get_prefs(db)
    if prefs["default_watchlist_id"] in (None, wid):
        remaining = list_watchlists(db)
        update_prefs(db, {"default_watchlist_id": remaining[0].id if remaining else None})


async def add_symbol(db: Session, settings: Settings, market: MarketDataService, wid: int, symbol: str) -> Watchlist:
    w = get_watchlist(db, wid)
    if len(w.items) >= settings.max_watchlist_items:
        raise AppError(409, "limit_reached", f"A watchlist can hold up to {settings.max_watchlist_items} symbols.")
    inst = await resolve_instrument(db, market, symbol)
    if any(it.instrument_id == inst.id for it in w.items):
        raise AppError(409, "already_present", f"{inst.symbol} is already in {w.name}.")
    pos = max((it.position for it in w.items), default=-1) + 1
    w.items.append(WatchlistItem(instrument_id=inst.id, position=pos))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "already_present", f"{inst.symbol} is already in {w.name}.") from exc
    db.refresh(w)
    return w


def remove_symbol(db: Session, market: MarketDataService, wid: int, symbol: str) -> Watchlist:
    w = get_watchlist(db, wid)
    sym = validate_symbol(market, symbol)
    item = next((it for it in w.items if it.instrument.symbol == sym), None)
    if item is None:
        raise AppError(404, "not_found", f"{sym} is not in {w.name}.")
    w.items.remove(item)
    db.commit()
    db.refresh(w)
    return w


def reorder(db: Session, wid: int, symbols: list[str]) -> Watchlist:
    w = get_watchlist(db, wid)
    current = {it.instrument.symbol: it for it in w.items}
    if sorted(symbols) != sorted(current):
        raise AppError(422, "validation_error", "Reorder must list exactly the symbols in the watchlist.")
    for pos, sym in enumerate(symbols):
        current[sym].position = pos
    w.sort_key = "manual"
    db.commit()
    db.refresh(w)
    return w


def membership(db: Session, market: MarketDataService, symbol: str) -> list[int]:
    sym = validate_symbol(market, symbol)
    rows = db.scalars(
        select(WatchlistItem.watchlist_id)
        .join(Instrument, Instrument.id == WatchlistItem.instrument_id)
        .where(Instrument.symbol == sym, Instrument.provider == market.source)
    )
    return sorted(set(rows))

"""Workspace presets (M14): named start page + density + default watchlist + chart symbol, stored server-side in
app_settings so they survive reloads and devices. Applying one updates the preferences it names."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import AppSetting, Watchlist
from marketdesk.services.prefs import get_prefs, update_prefs

KEY = "workspaces"
MAX_WORKSPACES = 8
START_PAGES = [
    {"path": "/", "label": "Overview"},
    {"path": "/watchlists", "label": "Watchlists"},
    {"path": "/screener", "label": "Screener"},
    {"path": "/macro", "label": "Macro"},
    {"path": "/portfolio", "label": "Portfolio"},
    {"path": "/alerts", "label": "Alerts"},
    {"path": "/journal", "label": "Journal"},
    {"path": "/lab", "label": "Lab"},
]
_PATHS = {p["path"] for p in START_PAGES}
_SYMBOL = re.compile(r"^[A-Za-z0-9^=.:&_-]{1,32}$")
DEFAULTS = [
    {"id": "market", "name": "Market", "start": "/", "density": "comfortable"},
    {"id": "research", "name": "Research", "start": "/screener", "density": "compact"},
    {"id": "portfolio", "name": "Portfolio", "start": "/portfolio", "density": "comfortable"},
]


def _blank(d: dict) -> dict:
    return {"default_watchlist_id": None, "chart_symbol": None, **d}


def _load(db: Session) -> dict:
    row = db.get(AppSetting, KEY)
    if row is None or not isinstance(row.value, dict) or not row.value.get("items"):
        return {"active": None, "items": [_blank(d) for d in DEFAULTS]}
    return {"active": row.value.get("active"), "items": [_blank(i) for i in row.value["items"]]}


def _save(db: Session, data: dict) -> dict:
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=data))
    else:
        row.value = data
    db.commit()
    return data


def listing(db: Session) -> dict:
    return {**_load(db), "start_pages": START_PAGES}


def _validate(db: Session, body: dict, items: list[dict], own_id: str | None) -> dict:
    name = " ".join(body["name"].split())
    if not name:
        raise AppError(422, "bad_name", "Give the workspace a name.")
    if any(i["name"].lower() == name.lower() and i["id"] != own_id for i in items):
        raise AppError(409, "duplicate_name", f"A workspace named {name!r} already exists.")
    if body["start"] not in _PATHS:
        raise AppError(422, "bad_start", "Choose one of the listed start pages.")
    wl = body.get("default_watchlist_id")
    if wl is not None and db.get(Watchlist, wl) is None:
        raise AppError(404, "not_found", "Watchlist not found.")
    sym = (body.get("chart_symbol") or "").strip() or None
    if sym is not None and not _SYMBOL.match(sym):
        raise AppError(422, "bad_symbol", "Use a symbol such as RELIANCE.NS or AAPL.")
    return {"name": name, "start": body["start"], "density": body["density"], "default_watchlist_id": wl,
            "chart_symbol": sym}  # fmt: skip


def create(db: Session, body: dict, capture: bool) -> dict:
    data = _load(db)
    if len(data["items"]) >= MAX_WORKSPACES:
        raise AppError(422, "too_many", f"Up to {MAX_WORKSPACES} workspaces.")
    if capture:  # "save the current layout": take the current preferences
        p = get_prefs(db)
        body = {**body, "density": p["density"], "default_watchlist_id": p["default_watchlist_id"],
                "chart_symbol": p["chart_symbol"]}  # fmt: skip
    clean = _validate(db, body, data["items"], None)
    taken = {i["id"] for i in data["items"]}
    n = 1
    while f"w{n}" in taken:
        n += 1
    item = {"id": f"w{n}", **clean}
    data["items"].append(item)
    _save(db, data)
    return item


def replace(db: Session, wid: str, body: dict) -> dict:
    data = _load(db)
    for i, it in enumerate(data["items"]):
        if it["id"] == wid:
            data["items"][i] = {"id": wid, **_validate(db, body, data["items"], wid)}
            _save(db, data)
            return data["items"][i]
    raise AppError(404, "not_found", "Workspace not found.")


def delete(db: Session, wid: str) -> None:
    data = _load(db)
    items = [i for i in data["items"] if i["id"] != wid]
    if len(items) == len(data["items"]):
        raise AppError(404, "not_found", "Workspace not found.")
    if not items:
        raise AppError(409, "last_workspace", "Keep at least one workspace.")
    _save(db, {"active": data["active"] if data["active"] != wid else None, "items": items})


def apply(db: Session, wid: str) -> dict:
    data = _load(db)
    ws = next((i for i in data["items"] if i["id"] == wid), None)
    if ws is None:
        raise AppError(404, "not_found", "Workspace not found.")
    notes: list[str] = []
    patch: dict = {"density": ws["density"]}
    if ws["default_watchlist_id"] is not None:
        if db.get(Watchlist, ws["default_watchlist_id"]) is None:
            notes.append("Its default watchlist was deleted; the current default is kept.")
        else:
            patch["default_watchlist_id"] = ws["default_watchlist_id"]
    if ws["chart_symbol"]:
        patch["chart_symbol"] = ws["chart_symbol"]
    prefs = update_prefs(db, patch)
    data["active"] = wid
    _save(db, data)
    return {"workspace": ws, "prefs": prefs, "notes": notes}

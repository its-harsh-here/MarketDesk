"""User preferences and small runtime state stored in app_settings."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.db import db_session
from marketdesk.models import AppSetting, Watchlist
from marketdesk.providers.fixture import FixtureState

PREF_DEFAULTS = {
    "theme": "dark",
    "density": "comfortable",
    "default_watchlist_id": None,
    "chart_symbol": None,
    "display_timezone": "Asia/Kolkata",
}
FIXTURE_KEY = "fixture_state"


def get_prefs(db: Session) -> dict:
    row = db.get(AppSetting, "prefs")
    prefs = dict(PREF_DEFAULTS)
    if row is not None and isinstance(row.value, dict):
        prefs.update({k: v for k, v in row.value.items() if k in PREF_DEFAULTS})
    if prefs["default_watchlist_id"] is not None and db.get(Watchlist, prefs["default_watchlist_id"]) is None:
        prefs["default_watchlist_id"] = None
    return prefs


def update_prefs(db: Session, patch: dict) -> dict:
    current = get_prefs(db)
    if "display_timezone" in patch and patch["display_timezone"] is not None:
        try:
            ZoneInfo(patch["display_timezone"])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise AppError(422, "validation_error", "Unknown timezone.", {"fields": [
                {"field": "display_timezone", "message": "Use an IANA timezone such as Asia/Kolkata."}]}) from exc
    if patch.get("default_watchlist_id") is not None and db.get(Watchlist, patch["default_watchlist_id"]) is None:
        raise AppError(404, "not_found", "Watchlist not found.")
    current.update({k: v for k, v in patch.items() if k in PREF_DEFAULTS})
    row = db.get(AppSetting, "prefs")
    if row is None:
        db.add(AppSetting(key="prefs", value=current))
    else:
        row.value = dict(current)
    db.commit()
    return current


def read_fixture_state(db: Session) -> FixtureState:
    row = db.get(AppSetting, FIXTURE_KEY)
    if row is None or not isinstance(row.value, dict):
        return FixtureState()
    return FixtureState(cursor_index=int(row.value.get("cursor_index", 0)), fault=bool(row.value.get("fault", False)))


def write_fixture_state(db: Session, state: FixtureState) -> None:
    row = db.get(AppSetting, FIXTURE_KEY)
    value = {"cursor_index": state.cursor_index, "fault": state.fault}
    if row is None:
        db.add(AppSetting(key=FIXTURE_KEY, value=value))
    else:
        row.value = value
    db.commit()


def fixture_state_getter() -> FixtureState:
    """Used by FixtureProvider (web and worker processes share state through the database)."""
    try:
        with db_session() as db:
            return read_fixture_state(db)
    except Exception:  # tables missing before migration: behave like the base dataset
        return FixtureState()

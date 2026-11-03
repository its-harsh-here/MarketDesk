"""User preferences and small runtime state stored in app_settings."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import event
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


_MEMO = "md_prefs"


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _forget_prefs(session: Session) -> None:
    session.info.pop(_MEMO, None)
    session.info.pop(_MEMO + "_watchlist", None)
    session.info.pop(_MEMO + "_row", None)


def get_prefs(db: Session) -> dict:
    # Read once per request (several services ask for the timezone or default watchlist); a commit
    # or rollback forgets the memo so a later read sees the new state.
    memo = db.info.get(_MEMO)
    if memo is not None:
        return dict(memo)
    row = db.get(AppSetting, "prefs")
    prefs = dict(PREF_DEFAULTS)
    if row is not None and isinstance(row.value, dict):
        prefs.update({k: v for k, v in row.value.items() if k in PREF_DEFAULTS})
    default = None
    if prefs["default_watchlist_id"] is not None:
        default = db.get(Watchlist, prefs["default_watchlist_id"])
        if default is None:
            prefs["default_watchlist_id"] = None
    # Holding the watchlist keeps it in the session's (weak) identity map for later lookups.
    db.info[_MEMO] = dict(prefs)
    db.info[_MEMO + "_watchlist"] = default
    return prefs


def display_timezone(db: Session) -> str:
    """The display timezone alone (skips the default-watchlist check that get_prefs performs)."""
    memo = db.info.get(_MEMO)
    if memo is not None:
        return memo["display_timezone"]
    row = db.get(AppSetting, "prefs")
    db.info[_MEMO + "_row"] = row  # keeps it in the identity map for a later get_prefs in this request
    value = row.value.get("display_timezone") if row is not None and isinstance(row.value, dict) else None
    return value or PREF_DEFAULTS["display_timezone"]


def update_prefs(db: Session, patch: dict) -> dict:
    current = get_prefs(db)
    if "display_timezone" in patch and patch["display_timezone"] is not None:
        try:
            ZoneInfo(patch["display_timezone"])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise AppError(
                422,
                "validation_error",
                "Unknown timezone.",
                {"fields": [{"field": "display_timezone", "message": "Use an IANA timezone such as Asia/Kolkata."}]},
            ) from exc
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

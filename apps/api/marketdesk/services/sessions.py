"""Market session states from published exchange calendars (exchange_calendars), never from weekday/time alone.

States: open, closed (with the reason: weekend, holiday, before the open, after the close) and unknown (outside the
calendar's data, a special session whose hours are not modelled, or a venue without a verified calendar). Times are
UTC instants; the calendar applies each exchange's timezone and daylight-saving rules (America/New_York changes
twice a year, Asia/Kolkata does not). A session state says what the exchange schedule is; it does not prove that a
quote is live.
"""

from __future__ import annotations

import functools
import importlib.metadata
from datetime import UTC, date, datetime

import exchange_calendars as xc
import pandas as pd

from marketdesk.providers.venues import MARKETS

CALENDAR_LIBRARY = f"exchange_calendars {importlib.metadata.version('exchange-calendars')}"

# Sessions held outside the regular schedule whose hours the calendar does not model. Shown as "unknown" rather than
# "closed". Sources: exchange announcements as reported by brokers (Budget-day session; Diwali Muhurat trading).
SPECIAL_SESSIONS: dict[str, dict[date, str]] = {
    "XBOM": {
        date(2026, 2, 1): "Union Budget special trading session",
        date(2026, 11, 8): "Muhurat trading (Diwali); the exchange announces its timing separately",
    },
}


@functools.cache
def _calendar(code: str):
    return xc.get_calendar(code, start="2020-01-01")


def calendar_bounds(code: str) -> tuple[date, date]:
    cal = _calendar(code)
    return cal.first_session.date(), cal.last_session.date()


def _iso(ts) -> str | None:
    return None if ts is None else pd.Timestamp(ts).tz_convert("UTC").to_pydatetime().isoformat()


def session_state(code: str | None, at: datetime | None = None) -> dict:
    at = (at or datetime.now(UTC)).astimezone(UTC)
    base = {"calendar": code, "source": CALENDAR_LIBRARY, "as_of": at.isoformat()}
    if not code:
        return {**base, "state": "unknown", "reason": "No verified trading calendar for this venue."}
    cal = _calendar(code)
    local_day = pd.Timestamp(at).tz_convert(cal.tz).date()
    first, last = calendar_bounds(code)
    if not (first <= local_day <= last):
        return {
            **base,
            "state": "unknown",
            "reason": f"Outside the calendar's published data ({first.isoformat()} to {last.isoformat()}).",
        }
    special = SPECIAL_SESSIONS.get(code, {}).get(local_day)
    if special:
        return {**base, "state": "unknown", "reason": f"{special}: special-session hours are not modelled."}
    ts = pd.Timestamp(at)
    day = pd.Timestamp(local_day)
    next_open = None
    try:
        next_open = cal.next_open(ts)
    except Exception:  # beyond the calendar's data
        next_open = None
    if cal.is_session(day):
        opens, closes = cal.session_open(day), cal.session_close(day)
        early = day in cal.early_closes if len(cal.early_closes) else False
        if opens <= ts < closes:
            return {
                **base,
                "state": "open",
                "reason": "Early close today." if early else "Regular session.",
                "opens_at": _iso(opens),
                "closes_at": _iso(closes),
            }
        reason = "Before the open." if ts < opens else "After the close."
        return {**base, "state": "closed", "reason": reason, "next_open": _iso(opens if ts < opens else next_open)}
    reason = "Weekend." if local_day.weekday() >= 5 else "Exchange holiday."
    return {**base, "state": "closed", "reason": reason, "next_open": _iso(next_open)}


def market_sessions(at: datetime | None = None) -> list[dict]:
    out = []
    for key, m in MARKETS.items():
        out.append({"market": key, "name": m["name"], "timezone": m["timezone"], **session_state(m["calendar"], at)})
    return out

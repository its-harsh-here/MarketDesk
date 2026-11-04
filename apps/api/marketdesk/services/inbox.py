"""Unified inbox: alert events and stored briefings in one time-ordered list, with read state.

Alert notices held by quiet hours are not shown until their release time. Filters: type, market, unread.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Alert, AlertEvent, Briefing, Instrument
from marketdesk.providers.venues import MARKETS
from marketdesk.services.alerts import _deliveries_for, delivered_filter, describe, event_dict
from marketdesk.services.briefings import briefing_dict, market_of

TYPES = ("alert", "briefing")


def _alert_rows(db: Session, market: str | None, unread: bool, limit: int) -> list[dict]:
    q = (
        select(AlertEvent, Alert, Instrument)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .join(Instrument, Instrument.id == Alert.instrument_id)
        .where(delivered_filter())
    )
    if unread:
        q = q.where(AlertEvent.read_at.is_(None))
    if market:
        tzs = MARKETS[market]["timezone"]
        q = q.where((Instrument.country == market) | (Instrument.country.is_(None) & (Instrument.timezone == tzs)))
    rows = db.execute(q.order_by(AlertEvent.triggered_at.desc()).limit(limit)).all()
    dels = _deliveries_for(db, [ev.id for ev, _, _ in rows])
    out = []
    for ev, a, inst in rows:
        d = event_dict(ev, inst.symbol, dels.get(ev.id))
        out.append(
            {
                "type": "alert",
                "id": ev.id,
                "at": ev.triggered_at,
                "read_at": ev.read_at,
                "market": market_of(inst),
                "title": f"{inst.symbol}: {describe(a)}",
                "alert": d,
                "briefing": None,
            }
        )
    return out


def _briefing_rows(db: Session, market: str | None, unread: bool, limit: int) -> list[dict]:
    q = select(Briefing)
    if unread:
        q = q.where(Briefing.read_at.is_(None))
    if market:
        q = q.where(Briefing.market == market)
    out = []
    for b in db.scalars(q.order_by(Briefing.created_at.desc()).limit(limit)):
        d = briefing_dict(b)
        out.append(
            {
                "type": "briefing",
                "id": b.id,
                "at": b.created_at,
                "read_at": b.read_at,
                "market": b.market,
                "title": d["title"],
                "alert": None,
                "briefing": d,
            }
        )
    return out


def list_inbox(db: Session, type_: str | None, market: str | None, unread: bool, limit: int) -> list[dict]:
    if market is not None and market not in MARKETS:
        raise AppError(422, "validation_error", f"Unknown market {market}.")
    rows: list[dict] = []
    if type_ in (None, "alert"):
        rows += _alert_rows(db, market, unread, limit)
    if type_ in (None, "briefing"):
        rows += _briefing_rows(db, market, unread, limit)
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:limit]


def unread_counts(db: Session) -> dict:
    alerts = db.scalar(
        select(func.count()).select_from(AlertEvent).where(AlertEvent.read_at.is_(None), delivered_filter())
    )
    held = db.scalar(
        select(func.count())
        .select_from(AlertEvent)
        .where(AlertEvent.read_at.is_(None), AlertEvent.deliver_after > datetime.now(UTC))
    )
    briefings = db.scalar(select(func.count()).select_from(Briefing).where(Briefing.read_at.is_(None)))
    return {"alerts": alerts or 0, "briefings": briefings or 0, "total": (alerts or 0) + (briefings or 0), "held": held}


def mark_read(db: Session, type_: str | None = None, item_id: int | None = None) -> int:
    """Mark one item (type + id) or everything delivered (no arguments) as read."""
    now = datetime.now(UTC)
    if item_id is not None and type_ not in TYPES:
        raise AppError(422, "validation_error", "Give the item type (alert or briefing) with its id.")
    updated = 0
    if type_ in (None, "alert"):
        stmt = update(AlertEvent).where(AlertEvent.read_at.is_(None), delivered_filter(now))
        if item_id is not None:
            stmt = stmt.where(AlertEvent.id == item_id)
        updated += db.execute(stmt.values(read_at=now)).rowcount or 0
    if type_ in (None, "briefing"):
        stmt = update(Briefing).where(Briefing.read_at.is_(None))
        if item_id is not None:
            stmt = stmt.where(Briefing.id == item_id)
        updated += db.execute(stmt.values(read_at=now)).rowcount or 0
    db.commit()
    if item_id is not None and updated == 0:
        model = AlertEvent if type_ == "alert" else Briefing
        if db.get(model, item_id) is None:
            raise AppError(404, "not_found", "Inbox item not found.")
    return updated

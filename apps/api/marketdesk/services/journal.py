"""Investment journal: the owner's own notes (plain text; never presented as advice)."""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Instrument, JournalEntry, JournalTag
from marketdesk.services.instruments import instrument_dict, resolve_instrument
from marketdesk.services.market import MarketDataService

_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9 _\-]{0,31}$")


def normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for raw in tags:
        t = " ".join(raw.strip().lower().split())
        if not t:
            continue
        if not _TAG_RE.match(t):
            raise AppError(
                422,
                "validation_error",
                f"Invalid tag '{raw[:40]}'.",
                {
                    "fields": [
                        {
                            "field": "tags",
                            "message": "Tags use letters, numbers, spaces, '-' or '_' (max 32 characters).",
                        }
                    ]
                },
            )
        if t not in out:
            out.append(t)
    return out


def entry_dict(e: JournalEntry, today: date) -> dict:
    return {
        "id": e.id,
        "symbol": e.instrument.symbol,
        "instrument": instrument_dict(e.instrument),
        "entry_date": e.entry_date,
        "title": e.title,
        "thesis": e.thesis,
        "risks": e.risks,
        "invalidation": e.invalidation,
        "tags": [t.tag for t in e.tags],
        "review_date": e.review_date,
        "review_due": bool(e.review_date and e.review_date <= today),
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


async def create_entry(db: Session, market: MarketDataService, payload: dict) -> JournalEntry:
    inst = await resolve_instrument(db, market, payload["symbol"])
    tags = normalize_tags(payload.get("tags") or [])
    _check_dates(payload)
    e = JournalEntry(
        instrument_id=inst.id,
        entry_date=payload["entry_date"],
        title=payload["title"].strip(),
        thesis=payload.get("thesis") or "",
        risks=payload.get("risks") or "",
        invalidation=payload.get("invalidation") or "",
        review_date=payload.get("review_date"),
    )
    e.tags = [JournalTag(tag=t) for t in tags]
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def _check_dates(payload: dict) -> None:
    if payload.get("review_date") and payload["review_date"] < payload["entry_date"]:
        raise AppError(
            422,
            "validation_error",
            "Review date cannot be before the entry date.",
            {"fields": [{"field": "review_date", "message": "Choose a date on or after the entry date."}]},
        )
    if not payload["title"].strip():
        raise AppError(
            422,
            "validation_error",
            "Title is required.",
            {"fields": [{"field": "title", "message": "Title is required."}]},
        )


async def update_entry(db: Session, market: MarketDataService, eid: int, payload: dict) -> JournalEntry:
    e = db.get(JournalEntry, eid)
    if e is None:
        raise AppError(404, "not_found", "Journal entry not found.")
    inst = await resolve_instrument(db, market, payload["symbol"])
    tags = normalize_tags(payload.get("tags") or [])
    _check_dates(payload)
    e.instrument_id = inst.id
    e.instrument = inst
    e.entry_date = payload["entry_date"]
    e.title = payload["title"].strip()
    e.thesis = payload.get("thesis") or ""
    e.risks = payload.get("risks") or ""
    e.invalidation = payload.get("invalidation") or ""
    e.review_date = payload.get("review_date")
    existing = {t.tag: t for t in e.tags}
    e.tags = [existing.get(t) or JournalTag(tag=t) for t in tags]
    db.commit()
    db.refresh(e)
    return e


def delete_entry(db: Session, eid: int) -> None:
    e = db.get(JournalEntry, eid)
    if e is None:
        raise AppError(404, "not_found", "Journal entry not found.")
    db.delete(e)
    db.commit()


def list_entries(
    db: Session, today: date, symbol: str | None, tag: str | None, q: str | None, limit: int, offset: int
) -> dict:
    stmt = select(JournalEntry).join(Instrument, Instrument.id == JournalEntry.instrument_id)
    if symbol:
        stmt = stmt.where(Instrument.symbol == symbol.strip().upper())
    if tag:
        stmt = stmt.where(JournalEntry.tags.any(JournalTag.tag == tag.strip().lower()))
    if q:
        like = f"%{q.strip()[:80]}%"
        stmt = stmt.where(
            or_(
                JournalEntry.title.ilike(like),
                JournalEntry.thesis.ilike(like),
                JournalEntry.risks.ilike(like),
                JournalEntry.invalidation.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc()).limit(limit).offset(offset))
    # Filter facets in one round trip.
    facets = db.execute(
        union_all(
            select(literal("tag").label("facet"), JournalTag.tag.label("value")),
            select(literal("symbol").label("facet"), Instrument.symbol.label("value")).join(
                JournalEntry, JournalEntry.instrument_id == Instrument.id
            ),
        )
    ).all()
    tags = sorted({v for f, v in facets if f == "tag"})
    symbols = sorted({v for f, v in facets if f == "symbol"})
    return {"items": [entry_dict(e, today) for e in rows], "total": total, "tags": tags, "symbols": symbols}

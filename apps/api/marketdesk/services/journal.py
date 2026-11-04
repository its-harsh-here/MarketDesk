"""Decision journal: the owner's own theses (plain text; never presented as advice).

- An entry's thesis fields are versioned. Version 1 is the original; every edit that changes the thesis must say what
  changed and why, and becomes a new immutable version. Versions and reviews are never updated after insert.
- Each version and each review stores the evidence observed at that moment (price with its market time and status,
  a few fundamentals, recent SEC filings for US listings). Today's data is fetched for comparison only and never
  replaces a stored snapshot.
- Tags and the next review date are scheduling/organising metadata and can change without a new version.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Instrument, JournalEntry, JournalReview, JournalTag, JournalVersion
from marketdesk.services.instruments import instrument_dict, resolve_instrument
from marketdesk.services.market import MarketDataService

log = logging.getLogger("marketdesk.journal")
DECISIONS = ("WATCH", "BUY", "ADD", "HOLD", "TRIM", "SELL", "AVOID")
OUTCOMES = ("intact", "weakened", "invalidated", "closed")
VERSIONED = ("entry_date", "title", "thesis", "risks", "invalidation", "decision", "conviction", "horizon")
USABLE = {"sample", "available", "cached", "stale"}

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
        "decision": e.decision,
        "conviction": e.conviction,
        "horizon": e.horizon,
        "version": e.version,
        "tags": [t.tag for t in e.tags],
        "review_date": e.review_date,
        "review_due": bool(e.review_date and e.review_date <= today),
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


def _bad(field: str, message: str) -> AppError:
    return AppError(422, "validation_error", message, {"fields": [{"field": field, "message": message}]})


def _content(payload: dict) -> dict:
    """The versioned thesis fields, normalised (what a version stores)."""
    decision = (payload.get("decision") or "").upper() or None
    if decision is not None and decision not in DECISIONS:
        raise _bad("decision", f"Decision must be one of {', '.join(DECISIONS)}.")
    conviction = payload.get("conviction")
    if conviction is not None and not 1 <= int(conviction) <= 5:
        raise _bad("conviction", "Conviction is 1 (low) to 5 (high).")
    horizon = (payload.get("horizon") or "").strip() or None
    return {
        "entry_date": payload["entry_date"].isoformat(),
        "title": payload["title"].strip(),
        "thesis": payload.get("thesis") or "",
        "risks": payload.get("risks") or "",
        "invalidation": payload.get("invalidation") or "",
        "decision": decision,
        "conviction": int(conviction) if conviction is not None else None,
        "horizon": horizon[:40] if horizon else None,
    }


def _plain(d: Decimal | None) -> str | None:
    return None if d is None else format(d.normalize(), "f")


async def capture_evidence(db: Session, market: MarketDataService, inst: Instrument, research=None) -> dict:
    """What the data showed now: price (with market time and status), fundamentals, recent SEC filings (US)."""
    now = datetime.now(UTC)
    ev: dict = {"captured": True, "captured_at": now.isoformat(), "symbol": inst.symbol, "provider": market.source}
    q = await market.quote(inst.symbol)
    if q.value is not None and q.meta.status in USABLE:
        ev["price"] = {
            "value": _plain(q.value.last_price),
            "currency": q.value.instrument.currency,
            "market_time": q.value.market_time.isoformat(),
            "session_date": q.value.session_date.isoformat() if q.value.session_date else None,
            "status": q.meta.status,
        }
    else:
        ev["price"] = {"value": None, "status": q.meta.status, "message": q.meta.message}
    f = await market.fundamentals(inst.symbol)
    if f.value is not None:
        v = f.value
        ev["fundamentals"] = {
            "market_cap": _plain(v.market_cap),
            "pe_ratio": _plain(v.pe_ratio),
            "dividend_yield_percent": _plain(v.dividend_yield_percent),
            "price_to_book": _plain(v.price_to_book),
            "currency": v.instrument.currency,
            "status": f.meta.status,
            "fetched_at": f.meta.fetched_at.isoformat() if f.meta.fetched_at else None,
        }
    else:
        ev["fundamentals"] = {"status": f.meta.status, "message": f.meta.message}
    if inst.country != "US":
        ev["filings"] = {"status": "not_applicable", "items": []}
    elif research is None or not research.client.enabled:
        ev["filings"] = {"status": "not_configured", "items": []}
    else:
        try:
            env = research.filings(db, inst, limit=5)
            items = [
                {
                    "form": x["form"],
                    "filing_date": x["filing_date"],
                    "accession": x["accession"],
                    "link": x.get("document_url") or x.get("index_url"),
                }
                for x in (env.get("data") or [])[:5]
            ]
            ev["filings"] = {"status": env.get("status"), "items": items}
        except Exception as exc:  # evidence capture must never block saving the owner's note
            log.warning("filings snapshot failed: %s", type(exc).__name__)
            ev["filings"] = {"status": "unavailable", "items": []}
    return ev


def _version_dict(v: JournalVersion) -> dict:
    return {
        "version": v.version,
        "created_at": v.created_at,
        "change_note": v.change_note,
        "content": v.content,
        "evidence": v.evidence,
    }


def _review_dict(r: JournalReview) -> dict:
    return {
        "id": r.id,
        "reviewed_at": r.reviewed_at,
        "outcome": r.outcome,
        "notes": r.notes,
        "version": r.version,
        "scheduled_for": r.scheduled_for,
        "next_review_date": r.next_review_date,
        "evidence": r.evidence,
    }


def get_entry(db: Session, eid: int) -> JournalEntry:
    e = db.get(JournalEntry, eid)
    if e is None:
        raise AppError(404, "not_found", "Journal entry not found.")
    return e


def _versions(db: Session, eid: int) -> list[JournalVersion]:
    return list(
        db.scalars(select(JournalVersion).where(JournalVersion.entry_id == eid).order_by(JournalVersion.version))
    )


def detail(db: Session, eid: int, today: date) -> dict:
    e = get_entry(db, eid)
    reviews = db.scalars(
        select(JournalReview).where(JournalReview.entry_id == eid).order_by(JournalReview.reviewed_at.desc())
    )
    return {
        **entry_dict(e, today),
        "versions": [_version_dict(v) for v in _versions(db, eid)],
        "reviews": [_review_dict(r) for r in reviews],
    }


def _apply_content(e: JournalEntry, c: dict) -> None:
    e.entry_date = date.fromisoformat(c["entry_date"])
    e.title, e.thesis, e.risks, e.invalidation = c["title"], c["thesis"], c["risks"], c["invalidation"]
    e.decision, e.conviction, e.horizon = c["decision"], c["conviction"], c["horizon"]


async def create_entry(db: Session, market: MarketDataService, payload: dict, research=None) -> JournalEntry:
    inst = await resolve_instrument(db, market, payload["symbol"])
    tags = normalize_tags(payload.get("tags") or [])
    _check_dates(payload)
    content = _content(payload)
    evidence = await capture_evidence(db, market, inst, research)
    e = JournalEntry(instrument_id=inst.id, review_date=payload.get("review_date"), version=1)
    _apply_content(e, content)
    e.tags = [JournalTag(tag=t) for t in tags]
    db.add(e)
    db.flush()
    db.add(JournalVersion(entry_id=e.id, version=1, change_note=None, content=content, evidence=evidence))
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


async def update_entry(db: Session, market: MarketDataService, eid: int, payload: dict, research=None) -> JournalEntry:
    """Tags and the review date change in place; a changed thesis becomes a new version with a change note."""
    e = get_entry(db, eid)
    inst = await resolve_instrument(db, market, payload["symbol"])
    if inst.id != e.instrument_id:
        raise _bad(
            "symbol", "A note's instrument cannot change: its versions and evidence refer to it. Write a new note."
        )
    tags = normalize_tags(payload.get("tags") or [])
    _check_dates(payload)
    content = _content(payload)
    latest = _versions(db, eid)[-1:]
    changed = not latest or any(latest[0].content.get(k) != content[k] for k in VERSIONED)
    if changed:
        note = (payload.get("change_note") or "").strip()
        if not note:
            raise _bad("change_note", "Say what changed and why; the previous version is kept unchanged.")
        evidence = await capture_evidence(db, market, inst, research)
        e.version += 1
        _apply_content(e, content)
        db.add(
            JournalVersion(entry_id=e.id, version=e.version, change_note=note[:500], content=content, evidence=evidence)
        )
    e.review_date = payload.get("review_date")
    existing = {t.tag: t for t in e.tags}
    e.tags = [existing.get(t) or JournalTag(tag=t) for t in tags]
    try:
        db.commit()
    except IntegrityError as exc:  # two edits raced for the same version number
        db.rollback()
        raise AppError(409, "conflict", "This note changed while you were editing it. Reload and try again.") from exc
    db.refresh(e)
    return e


def delete_entry(db: Session, eid: int) -> None:
    db.delete(get_entry(db, eid))
    db.commit()


async def add_review(db: Session, market: MarketDataService, eid: int, payload: dict, today: date, research=None):
    e = get_entry(db, eid)
    outcome = payload["outcome"]
    if outcome not in OUTCOMES:
        raise _bad("outcome", f"Outcome must be one of {', '.join(OUTCOMES)}.")
    nxt = payload.get("next_review_date")
    if nxt is not None and nxt <= today:
        raise _bad("next_review_date", "The next review must be after today.")
    evidence = await capture_evidence(db, market, e.instrument, research)
    r = JournalReview(
        entry_id=e.id,
        outcome=outcome,
        notes=(payload.get("notes") or "").strip(),
        version=e.version,
        scheduled_for=e.review_date,
        next_review_date=nxt,
        evidence=evidence,
    )
    db.add(r)
    e.review_date = nxt  # the queue moves to the next scheduled review (or none)
    db.commit()
    db.refresh(r)
    return r


async def compare(db: Session, market: MarketDataService, eid: int, version: int | None, research=None) -> dict:
    """A stored version's evidence beside today's (fetched now, not stored). Simple price change in the instrument's
    own currency; splits after the snapshot are flagged because they break a raw price comparison."""
    e = get_entry(db, eid)
    versions = _versions(db, eid)
    v = next((x for x in versions if x.version == (version or 1)), None)
    if v is None:
        raise AppError(404, "not_found", "No such version.")
    then = v.evidence or {}
    now = await capture_evidence(db, market, e.instrument, research)
    since = (datetime.fromisoformat(then["captured_at"]) if then.get("captured_at") else v.created_at).astimezone(UTC)
    tp, np_ = (then.get("price") or {}), now["price"]
    change = None
    note = "No price was captured with this version."
    if tp.get("value") and np_.get("value"):
        if tp.get("currency") != np_.get("currency"):
            note = "The prices are in different currencies; no change is computed."
        else:
            change = (Decimal(np_["value"]) / Decimal(tp["value"]) - 1) * 100
            note = f"Price change in {np_['currency']} from the version's snapshot to now; dividends are not included."
    splits = []
    acts = await market.actions(e.instrument.symbol)
    for a in acts.value or []:
        if a.kind == "SPLIT" and a.action_date > since.date():
            splits.append({"date": a.action_date, "description": a.description})
    if splits and change is not None:
        note += " A split happened since the snapshot, so the raw price change is not comparable."
        change = None
    filings_since = [
        x for x in (now.get("filings") or {}).get("items", []) if x["filing_date"] > since.date().isoformat()
    ]
    return {
        "version": v.version,
        "version_created_at": v.created_at,
        "then": then,
        "now": now,
        "price_change_pct": change,
        "price_note": note,
        "splits_since": splits,
        "filings_since": filings_since,
        "days_elapsed": (datetime.now(UTC) - since).days,
    }


def list_entries(
    db: Session,
    today: date,
    symbol: str | None,
    tag: str | None,
    q: str | None,
    limit: int,
    offset: int,
    due: bool = False,
) -> dict:
    stmt = select(JournalEntry).join(Instrument, Instrument.id == JournalEntry.instrument_id)
    if due:
        stmt = stmt.where(JournalEntry.review_date.is_not(None), JournalEntry.review_date <= today)
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
    order = (
        (JournalEntry.review_date, JournalEntry.id) if due else (JournalEntry.entry_date.desc(), JournalEntry.id.desc())
    )
    rows = db.scalars(stmt.order_by(*order).limit(limit).offset(offset))
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

"""Price alerts: sampled detection against distinct provider observations.

- An observation is identified by (instrument, provider, market timestamp); re-reading the same
  cached quote maps to the same observation and can never create a second event.
- An active alert fires at most once per arm (event key "<alert_id>:<arm_seq>", unique in the
  database), then deactivates until the owner rearms it.
- Only fresh provider results are evaluated: stale fallbacks and errors are skipped, and an
  observation from a different provider than the running one is ignored.
- This is sampled detection at the worker's polling interval, not tick-by-tick monitoring.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Alert, AlertEvent, Instrument, QuoteObservation
from marketdesk.providers.base import QuoteSnapshot
from marketdesk.services.instruments import instrument_dict, resolve_instrument
from marketdesk.services.ledger import places
from marketdesk.services.market import MarketDataService, Result

log = logging.getLogger("marketdesk.alerts")
EVALUABLE_STATUSES = {"sample", "available", "cached"}


def event_dict(ev: AlertEvent, symbol: str) -> dict:
    return {
        "id": ev.id,
        "alert_id": ev.alert_id,
        "symbol": symbol,
        "arm_seq": ev.arm_seq,
        "direction": ev.direction,
        "target_price": ev.target_price,
        "observed_price": ev.observed_price,
        "observed_market_time": ev.observed_market_time,
        "provider": ev.provider,
        "triggered_at": ev.triggered_at,
        "read_at": ev.read_at,
    }


def alert_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "symbol": a.instrument.symbol,
        "instrument": instrument_dict(a.instrument),
        "direction": a.direction,
        "target_price": a.target_price,
        "note": a.note,
        "active": a.active,
        "arm_seq": a.arm_seq,
        "armed_at": a.armed_at,
        "last_evaluated_at": a.last_evaluated_at,
        "last_observed_price": a.last_observed_price,
        "last_observed_market_time": a.last_observed_market_time,
        "created_at": a.created_at,
        "events": [event_dict(e, a.instrument.symbol) for e in a.events[:20]],
    }


def _check_target(value: Decimal) -> None:
    if value <= 0 or places(value) > 4:
        raise AppError(
            422,
            "validation_error",
            "Target price must be positive with at most 4 decimal places.",
            {"fields": [{"field": "target_price", "message": "Use a positive price (max 4 decimals)."}]},
        )


async def create_alert(db: Session, market: MarketDataService, payload: dict) -> Alert:
    _check_target(payload["target_price"])
    inst = await resolve_instrument(db, market, payload["symbol"])
    a = Alert(
        instrument_id=inst.id,
        direction=payload["direction"],
        target_price=payload["target_price"],
        note=(payload.get("note") or "").strip() or None,
        active=True,
        arm_seq=1,
        armed_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def get_alert(db: Session, aid: int) -> Alert:
    a = db.get(Alert, aid)
    if a is None:
        raise AppError(404, "not_found", "Alert not found.")
    return a


def update_alert(db: Session, aid: int, patch: dict) -> Alert:
    a = get_alert(db, aid)
    if patch.get("target_price") is not None:
        _check_target(patch["target_price"])
        a.target_price = patch["target_price"]
    if patch.get("direction") is not None:
        a.direction = patch["direction"]
    if "note" in patch and patch["note"] is not None:
        a.note = patch["note"].strip() or None
    if patch.get("active") is False:
        a.active = False  # paused without an event
    elif patch.get("active") is True and not a.active:
        _rearm(a)
    db.commit()
    db.refresh(a)
    return a


def _rearm(a: Alert) -> None:
    a.arm_seq += 1
    a.active = True
    a.armed_at = datetime.now(UTC)


def rearm_alert(db: Session, aid: int) -> Alert:
    a = get_alert(db, aid)
    if a.active:
        raise AppError(409, "already_armed", "This alert is already active.")
    _rearm(a)
    db.commit()
    db.refresh(a)
    return a


def delete_alert(db: Session, aid: int) -> None:
    db.delete(get_alert(db, aid))
    db.commit()


def list_alerts(db: Session) -> list[Alert]:
    return list(db.scalars(select(Alert).order_by(Alert.active.desc(), Alert.created_at.desc())))


def list_events(db: Session, limit: int, unread_only: bool = False) -> list[dict]:
    q = (
        select(AlertEvent, Instrument.symbol)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .join(Instrument, Instrument.id == Alert.instrument_id)
    )
    if unread_only:
        q = q.where(AlertEvent.read_at.is_(None))
    q = q.order_by(AlertEvent.triggered_at.desc()).limit(limit)
    return [event_dict(ev, sym) for ev, sym in db.execute(q)]


def mark_read(db: Session, event_id: int | None = None) -> int:
    stmt = update(AlertEvent).where(AlertEvent.read_at.is_(None))
    if event_id is not None:
        stmt = stmt.where(AlertEvent.id == event_id)
    res = db.execute(stmt.values(read_at=datetime.now(UTC)))
    db.commit()
    return res.rowcount or 0


# --------------------------------------------------------------------------- evaluation
def record_observation(
    db: Session, inst: Instrument, provider: str, q: QuoteSnapshot, fetched_at: datetime
) -> QuoteObservation:
    existing = db.scalar(
        select(QuoteObservation).where(
            QuoteObservation.instrument_id == inst.id,
            QuoteObservation.provider == provider,
            QuoteObservation.market_time == q.market_time,
        )
    )
    if existing is not None:
        return existing
    obs = QuoteObservation(
        instrument_id=inst.id, provider=provider, price=q.last_price, market_time=q.market_time, fetched_at=fetched_at
    )
    db.add(obs)
    try:
        db.commit()
    except IntegrityError:  # recorded concurrently by another process
        db.rollback()
        return db.scalar(
            select(QuoteObservation).where(
                QuoteObservation.instrument_id == inst.id,
                QuoteObservation.provider == provider,
                QuoteObservation.market_time == q.market_time,
            )
        )
    return obs


def matches(direction: str, target: Decimal, price: Decimal) -> bool:
    return price >= target if direction == "ABOVE" else price <= target


def evaluate_alert(db: Session, alert: Alert, obs: QuoteObservation, provider: str) -> AlertEvent | None:
    """Evaluate one active alert against one observation. Idempotent across restarts."""
    if not alert.active or obs.provider != provider or alert.instrument.provider != provider:
        return None
    if alert.last_observation_id == obs.id:
        return None  # this observation was already evaluated for this alert
    now = datetime.now(UTC)
    alert.last_evaluated_at = now
    alert.last_observation_id = obs.id
    alert.last_observed_price = obs.price
    alert.last_observed_market_time = obs.market_time
    event = None
    if matches(alert.direction, alert.target_price, obs.price):
        event = AlertEvent(
            alert_id=alert.id,
            arm_seq=alert.arm_seq,
            event_key=f"{alert.id}:{alert.arm_seq}",
            observation_id=obs.id,
            direction=alert.direction,
            target_price=alert.target_price,
            observed_price=obs.price,
            observed_market_time=obs.market_time,
            provider=provider,
            triggered_at=now,
        )
        db.add(event)
        alert.active = False
    try:
        db.commit()
    except IntegrityError:
        # The event for this arm already exists (e.g. a previous run crashed after writing it).
        db.rollback()
        db.refresh(alert)
        alert.active = False
        db.commit()
        return None
    return event


async def run_evaluation_cycle(db: Session, market: MarketDataService) -> dict:
    """Fetch quotes for instruments with active alerts, record observations, evaluate."""
    provider = market.source
    alerts = list(db.scalars(select(Alert).where(Alert.active.is_(True))))
    by_symbol: dict[str, list[Alert]] = {}
    for a in alerts:
        if a.instrument.provider == provider:
            by_symbol.setdefault(a.instrument.symbol, []).append(a)
    summary = {
        "active_alerts": len(alerts),
        "symbols": len(by_symbol),
        "evaluated": 0,
        "triggered": 0,
        "skipped": [],
        "provider": provider,
    }
    if not by_symbol:
        return summary
    results: dict[str, Result[QuoteSnapshot]] = await market.quotes(list(by_symbol))
    for sym, r in results.items():
        if r.value is None or r.meta.status not in EVALUABLE_STATUSES:
            summary["skipped"].append({"symbol": sym, "status": r.meta.status, "reason": r.meta.message})
            continue
        inst = by_symbol[sym][0].instrument
        obs = record_observation(db, inst, provider, r.value, r.meta.fetched_at or datetime.now(UTC))
        for a in by_symbol[sym]:
            db.refresh(a)
            before = a.last_observation_id
            ev = evaluate_alert(db, a, obs, provider)
            if before != obs.id:
                summary["evaluated"] += 1
            if ev is not None:
                summary["triggered"] += 1
                log.info("alert %s triggered", a.id)
    return summary

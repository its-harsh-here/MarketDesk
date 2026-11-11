"""Alerts: rule definitions, sampled evaluation, event identity, delivery and cooldown/rearm.

- PRICE and CROSS rules are evaluated against distinct provider observations, identified by (instrument, provider,
  market timestamp); re-reading the same cached quote maps to the same observation and cannot create a second event.
- VOLUME and VOLATILITY rules are evaluated once per completed daily session (see alert_rules for the method).
- FILING rules (US listings) watch SEC filings of the chosen forms; each accession is one event.
- An event's key is unique in the database: "<alert_id>:<arm_seq>" for price/session rules (fires once per arm),
  "<alert_id>:filing:<accession>" for filings. A worker restart or retry can therefore never duplicate an event.
- After firing, an alert waits to be rearmed: manually, or automatically after its cooldown. FILING rules stay active.
- Each event gets one delivery row per channel (unique), so a notice is never delivered twice. Only the in-app
  channel exists; during the alert's quiet hours the in-app notice is held until the window ends.
- Stale, failed or missing data is never evaluated; the reason is recorded on the alert.
- This is sampled detection at the worker's polling interval, not tick-by-tick monitoring.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Alert, AlertDelivery, AlertEvent, Instrument, QuoteObservation
from marketdesk.providers.base import QuoteSnapshot
from marketdesk.providers.venues import MARKETS
from marketdesk.services import alert_rules as rules
from marketdesk.services.instruments import instrument_dict, resolve_instrument
from marketdesk.services.ledger import places
from marketdesk.services.market import MarketDataService, Result
from marketdesk.services.prefs import display_timezone

log = logging.getLogger("marketdesk.alerts")
EVALUABLE_STATUSES = {"sample", "available", "cached"}
MAX_COOLDOWN_MINUTES = 7 * 24 * 60


class InAppChannel:
    name = "in_app"

    def deliver(self, event: AlertEvent) -> None:
        """The inbox reads events directly; recording the delivery is the delivery."""


# External channels (email, Telegram, push) are registered here only when configured. None are configured, and the
# UI says so; nothing is ever shown as sent through a channel that does not exist.
CHANNELS: dict[str, object] = {"in_app": InAppChannel()}


# --------------------------------------------------------------------------- serialisation
def describe(a: Alert) -> str:
    p = a.params or {}
    if a.rule == "CROSS":
        side = "above" if a.direction == "ABOVE" else "below"
        return f"Crosses {side} {rules.price_text(a.target_price)}"
    if a.rule == "VOLUME":
        return f"Session volume ≥ {rules.plain(a.target_price)}× {p.get('lookback', 20)}-session average"
    if a.rule == "VOLATILITY":
        return f"Daily move ≥ {rules.plain(a.target_price)} sd of prior {p.get('lookback', 20)} sessions"
    if a.rule == "FILING":
        return f"New SEC filing: {', '.join(p.get('forms') or rules.FILING_FORMS)}"
    if a.rule == "EARNINGS":
        return f"Results reminder {p.get('days_before', 3)} day(s) before the next results date"
    return f"Price {'at or above' if a.direction == 'ABOVE' else 'at or below'} {rules.price_text(a.target_price)}"


def event_dict(ev: AlertEvent, symbol: str, deliveries: list[AlertDelivery] | None = None) -> dict:
    return {
        "id": ev.id,
        "alert_id": ev.alert_id,
        "symbol": symbol,
        "arm_seq": ev.arm_seq,
        "rule": ev.rule,
        "direction": ev.direction,
        "target_price": ev.target_price,
        "observed_price": ev.observed_price,
        "observed_market_time": ev.observed_market_time,
        "provider": ev.provider,
        "triggered_at": ev.triggered_at,
        "read_at": ev.read_at,
        "explanation": ev.explanation,
        "link": ev.link,
        "deliver_after": ev.deliver_after,
        "deliveries": [
            {"channel": d.channel, "status": d.status, "attempts": d.attempts, "last_error": d.last_error}
            for d in (deliveries or [])
        ],
    }


def alert_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "symbol": a.instrument.symbol,
        "instrument": instrument_dict(a.instrument),
        "rule": a.rule,
        "description": describe(a),
        "direction": a.direction,
        "target_price": a.target_price,
        "params": a.params or {},
        "cooldown_minutes": a.cooldown_minutes,
        "rearm_at": a.rearm_at,
        "quiet_start": a.quiet_start,
        "quiet_end": a.quiet_end,
        "last_skip_reason": a.last_skip_reason,
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


# --------------------------------------------------------------------------- validation and CRUD
def _bad(field: str, message: str) -> AppError:
    return AppError(422, "validation_error", message, {"fields": [{"field": field, "message": message}]})


def _check_target(value: Decimal) -> None:
    if value <= 0 or places(value) > 4:
        raise _bad("target_price", "Target price must be positive with at most 4 decimal places.")


def _validate(payload: dict, inst: Instrument | None) -> dict:
    rule = payload.get("rule") or "PRICE"
    if rule not in rules.RULES:
        raise _bad("rule", f"Unknown rule {rule}.")
    params: dict = {}
    target = payload.get("target_price")
    if rule in ("PRICE", "CROSS"):
        if target is None:
            raise _bad("target_price", "Enter the price level.")
        _check_target(target)
    elif rule in ("VOLUME", "VOLATILITY"):
        if target is None or not Decimal("1.1") <= Decimal(target) <= Decimal("20"):
            raise _bad("target_price", "Enter a multiple between 1.1 and 20.")
        lookback = int((payload.get("params") or {}).get("lookback") or 20)
        if not 5 <= lookback <= 60:
            raise _bad("params.lookback", "Comparison window must be 5 to 60 sessions.")
        params["lookback"] = lookback
        payload["direction"] = "ABOVE"
    elif rule == "EARNINGS":
        days = int((payload.get("params") or {}).get("days_before") or 3)
        if not 0 <= days <= 30:
            raise _bad("params.days_before", "Remind 0 to 30 days before the date.")
        params["days_before"] = days
        payload["direction"], target = "ABOVE", Decimal("0")
    else:  # FILING
        if inst is not None and inst.country != "US":
            raise _bad("rule", "Filing alerts use SEC filings and are available for US listings only.")
        forms = [f for f in (payload.get("params") or {}).get("forms") or [] if f in rules.FILING_FORMS]
        params["forms"] = forms or ["10-K", "10-Q", "8-K"]
        payload["direction"], target = "ABOVE", Decimal("0")
    cooldown = payload.get("cooldown_minutes")
    if cooldown is not None and not 5 <= int(cooldown) <= MAX_COOLDOWN_MINUTES:
        raise _bad("cooldown_minutes", "Cooldown must be between 5 minutes and 7 days, or empty for manual rearm.")
    qs, qe = payload.get("quiet_start"), payload.get("quiet_end")
    if (qs or qe) and not (rules.valid_hhmm(qs) and rules.valid_hhmm(qe) and qs != qe):
        raise _bad("quiet_start", "Quiet hours need a start and an end time (HH:MM), and they must differ.")
    return {"rule": rule, "params": params, "target_price": target, "cooldown_minutes": cooldown, "qs": qs, "qe": qe}


async def create_alert(db: Session, market: MarketDataService, payload: dict) -> Alert:
    inst = await resolve_instrument(db, market, payload["symbol"])
    v = _validate(payload, inst)
    a = Alert(
        instrument_id=inst.id,
        rule=v["rule"],
        params=v["params"] or None,
        direction=payload["direction"],
        target_price=v["target_price"],
        cooldown_minutes=v["cooldown_minutes"],
        quiet_start=v["qs"] or None,
        quiet_end=v["qe"] or None,
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
        if a.rule in ("PRICE", "CROSS"):
            _check_target(patch["target_price"])
        elif a.rule in ("VOLUME", "VOLATILITY"):
            if not Decimal("1.1") <= Decimal(patch["target_price"]) <= Decimal("20"):
                raise _bad("target_price", "Enter a multiple between 1.1 and 20.")
        else:
            raise _bad("target_price", "Filing alerts have no level.")
        a.target_price = patch["target_price"]
    if patch.get("direction") is not None and a.rule in ("PRICE", "CROSS"):
        a.direction = patch["direction"]
    if "note" in patch and patch["note"] is not None:
        a.note = patch["note"].strip() or None
    if "cooldown_minutes" in patch:
        c = patch["cooldown_minutes"]
        if c is not None and not 5 <= int(c) <= MAX_COOLDOWN_MINUTES:
            raise _bad("cooldown_minutes", "Cooldown must be between 5 minutes and 7 days, or empty for manual rearm.")
        a.cooldown_minutes = c
    if "quiet_start" in patch or "quiet_end" in patch:
        qs, qe = patch.get("quiet_start"), patch.get("quiet_end")
        if (qs or qe) and not (rules.valid_hhmm(qs) and rules.valid_hhmm(qe) and qs != qe):
            raise _bad("quiet_start", "Quiet hours need a start and an end time (HH:MM), and they must differ.")
        a.quiet_start, a.quiet_end = qs or None, qe or None
    if patch.get("active") is False:
        a.active = False  # paused without an event
        a.rearm_at = None
    elif patch.get("active") is True and not a.active:
        _rearm(a)
    db.commit()
    db.refresh(a)
    return a


def _rearm(a: Alert) -> None:
    a.arm_seq += 1
    a.active = True
    a.armed_at = datetime.now(UTC)
    a.rearm_at = None


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


def _deliveries_for(db: Session, ids: list[int]) -> dict[int, list[AlertDelivery]]:
    out: dict[int, list[AlertDelivery]] = {}
    if ids:
        for d in db.scalars(select(AlertDelivery).where(AlertDelivery.event_id.in_(ids))):
            out.setdefault(d.event_id, []).append(d)
    return out


def delivered_filter(now: datetime | None = None):
    """Events whose in-app notice is not held by quiet hours."""
    now = now or datetime.now(UTC)
    return (AlertEvent.deliver_after.is_(None)) | (AlertEvent.deliver_after <= now)


def list_events(db: Session, limit: int, unread_only: bool = False) -> list[dict]:
    q = (
        select(AlertEvent, Instrument.symbol)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .join(Instrument, Instrument.id == Alert.instrument_id)
    )
    if unread_only:
        q = q.where(AlertEvent.read_at.is_(None), delivered_filter())
    rows = list(db.execute(q.order_by(AlertEvent.triggered_at.desc()).limit(limit)))
    dels = _deliveries_for(db, [ev.id for ev, _ in rows])
    return [event_dict(ev, sym, dels.get(ev.id)) for ev, sym in rows]


def mark_read(db: Session, event_id: int | None = None) -> int:
    stmt = update(AlertEvent).where(AlertEvent.read_at.is_(None), delivered_filter())
    if event_id is not None:
        stmt = stmt.where(AlertEvent.id == event_id)
    res = db.execute(stmt.values(read_at=datetime.now(UTC)))
    db.commit()
    return res.rowcount or 0


# --------------------------------------------------------------------------- firing
def _fire(
    db: Session,
    alert: Alert,
    *,
    key: str,
    provider: str,
    explanation: str,
    observed_price: Decimal | None = None,
    observed_time: datetime | None = None,
    observation_id: int | None = None,
    link: str | None = None,
    deactivate: bool = True,
) -> AlertEvent | None:
    """Create the event, its delivery rows and the rearm state in one transaction; a repeated key is a no-op."""
    now = datetime.now(UTC)
    hold = rules.quiet_release(now, alert.quiet_start, alert.quiet_end, display_timezone(db))
    event = AlertEvent(
        alert_id=alert.id,
        arm_seq=alert.arm_seq,
        event_key=key,
        observation_id=observation_id,
        rule=alert.rule,
        direction=alert.direction,
        target_price=alert.target_price if alert.rule in ("PRICE", "CROSS") else None,
        observed_price=observed_price,
        observed_market_time=observed_time,
        provider=provider,
        triggered_at=now,
        explanation=explanation,
        link=link,
        deliver_after=hold,
    )
    db.add(event)
    if deactivate:
        alert.active = False
        if alert.cooldown_minutes:
            alert.rearm_at = now + timedelta(minutes=alert.cooldown_minutes)
    try:
        db.flush()
        for name, channel in CHANNELS.items():
            delivery = AlertDelivery(
                event_id=event.id, channel=name, status="held" if hold else "delivered", attempts=0
            )
            if not hold:
                try:
                    channel.deliver(event)
                    delivery.attempts = 1
                except Exception as exc:  # a failed channel is recorded and visible, never shown as sent
                    delivery.status, delivery.attempts = "failed", 1
                    delivery.last_error = f"{type(exc).__name__}: {exc}"[:200]
            db.add(delivery)
        db.commit()
    except IntegrityError:
        # The event for this key already exists (e.g. a previous run crashed after writing it).
        db.rollback()
        db.refresh(alert)
        if deactivate and alert.active:
            alert.active = False
            db.commit()
        return None
    return event


def maintenance(db: Session, now: datetime | None = None) -> dict:
    """Auto-rearm alerts whose cooldown has passed, and release in-app notices held by quiet hours."""
    now = now or datetime.now(UTC)
    rearmed = 0
    for a in db.scalars(
        select(Alert).where(Alert.active.is_(False), Alert.rearm_at.is_not(None), Alert.rearm_at <= now)
    ):
        _rearm(a)
        rearmed += 1
    released = 0
    held = db.execute(
        select(AlertDelivery)
        .join(AlertEvent, AlertEvent.id == AlertDelivery.event_id)
        .where(AlertDelivery.status == "held", AlertEvent.deliver_after <= now)
    ).scalars()
    for d in held:
        d.status, d.attempts = "delivered", d.attempts + 1
        released += 1
    db.commit()
    return {"rearmed": rearmed, "released": released}


# --------------------------------------------------------------------------- observation rules
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
    """Evaluate one active PRICE or CROSS alert against one observation. Idempotent across restarts."""
    if not alert.active or alert.rule not in ("PRICE", "CROSS"):
        return None
    if obs.provider != provider or alert.instrument.provider != provider:
        return None
    if alert.last_observation_id == obs.id:
        return None  # this observation was already evaluated for this alert
    previous = alert.last_observed_price if alert.last_observation_id is not None else None
    alert.last_evaluated_at = datetime.now(UTC)
    alert.last_observation_id = obs.id
    alert.last_observed_price = obs.price
    alert.last_observed_market_time = obs.market_time
    alert.last_skip_reason = None
    if alert.rule == "PRICE":
        hit = matches(alert.direction, alert.target_price, obs.price)
        sign = "≥" if alert.direction == "ABOVE" else "≤"
        why = f"Observed {rules.price_text(obs.price)} ({sign} {rules.price_text(alert.target_price)})"
    else:
        hit = rules.crossed(alert.direction, alert.target_price, previous, obs.price)
        why = (
            f"Moved from {rules.price_text(previous) if previous is not None else '—'} to "
            f"{rules.price_text(obs.price)}, crossing {rules.price_text(alert.target_price)}"
        )
    if not hit:
        db.commit()
        return None
    stamp = obs.market_time.astimezone(UTC).strftime("%d %b %Y %H:%M UTC")
    explanation = f"{why}; market time {stamp}, source {provider}. Sampled, not tick-by-tick."
    return _fire(
        db,
        alert,
        key=f"{alert.id}:{alert.arm_seq}",
        provider=provider,
        explanation=explanation,
        observed_price=obs.price,
        observed_time=obs.market_time,
        observation_id=obs.id,
    )


# --------------------------------------------------------------------------- session and filing rules
def last_bar_complete(country: str | None, last_session: date, now: datetime) -> bool:
    """Is the most recent daily bar a finished session? Uses the exchange calendar; unknown means 'not yet'."""
    from marketdesk.services.sessions import session_state

    market = MARKETS.get(country or "")
    if market is None:
        return last_session < now.date() - timedelta(days=1)  # no calendar: only bars at least a day old
    state = session_state(market["calendar"], now)
    local_today = now.astimezone(ZoneInfo(market["timezone"])).date()
    if last_session < local_today:
        return True
    return state["state"] == "closed" and state["reason"] == "After the close."


def evaluate_session_rule(db: Session, alert: Alert, bars: list, provider: str, now: datetime) -> AlertEvent | None:
    if not alert.active or alert.rule not in ("VOLUME", "VOLATILITY") or not bars:
        return None
    usable = rules.completed_bars(bars, last_bar_complete(alert.instrument.country, bars[-1].session_date, now))
    lookback = int((alert.params or {}).get("lookback") or 20)
    signal = rules.volume_signal if alert.rule == "VOLUME" else rules.volatility_signal
    session, fired, text = signal(usable, lookback, alert.target_price)
    alert.last_evaluated_at = now
    if session is None:
        alert.last_skip_reason = text
        db.commit()
        return None
    marker = datetime(session.year, session.month, session.day, tzinfo=UTC)
    if alert.last_observed_market_time == marker:
        db.commit()
        return None  # this completed session was already evaluated
    alert.last_observed_market_time, alert.last_skip_reason = marker, None
    if not fired:
        db.commit()
        return None
    bar = usable[-1]
    return _fire(
        db,
        alert,
        key=f"{alert.id}:{alert.arm_seq}",
        provider=provider,
        explanation=f"{text} Source {provider} daily bars.",
        observed_price=bar.close,
        observed_time=marker,
    )


def evaluate_filings(db: Session, alert: Alert, filings: list[dict]) -> list[AlertEvent]:
    """One event per new filing (filed on or after the alert was armed) of the chosen forms."""
    if not alert.active or alert.rule != "FILING":
        return []
    forms = set((alert.params or {}).get("forms") or [])
    armed = alert.armed_at.date()
    out = []
    for f in filings:
        if f["form"] not in forms or not f.get("filing_date") or date.fromisoformat(f["filing_date"]) < armed:
            continue
        text = (
            f"{f['form']} filed {f['filing_date']}"
            + (f" for the period ending {f['report_date']}" if f.get("report_date") else "")
            + f" ({f.get('description') or f['form']}). Source: SEC EDGAR, accession {f['accession']}."
        )
        ev = _fire(
            db,
            alert,
            key=f"{alert.id}:filing:{f['accession']}",
            provider="sec",
            explanation=text,
            observed_time=datetime.fromisoformat(f["filing_date"]).replace(tzinfo=UTC),
            link=f.get("document_url") or f.get("index_url"),
            deactivate=False,
        )
        if ev is not None:
            out.append(ev)
    alert.last_evaluated_at, alert.last_skip_reason = datetime.now(UTC), None
    db.commit()
    return out


def evaluate_earnings(db: Session, alert: Alert, cal: dict, today: date) -> AlertEvent | None:
    """One reminder per (alert, next results date) once today is within `days_before` of it."""
    nxt = cal.get("next") or {}
    if not alert.active or alert.rule != "EARNINGS" or not nxt.get("date"):
        alert.last_skip_reason = None if nxt.get("date") else f"No next results date: {cal.get('note') or 'unknown'}"
        alert.last_evaluated_at = datetime.now(UTC)
        db.commit()
        return None
    due = date.fromisoformat(nxt["date"])
    days = int((alert.params or {}).get("days_before", 3))
    alert.last_evaluated_at, alert.last_skip_reason = datetime.now(UTC), None
    if not due - timedelta(days=days) <= today <= due:
        db.commit()
        return None
    kind = "deadline for results" if nxt.get("basis") == "deadline" else "estimated results date"
    text = f"{alert.instrument.symbol}: {kind} {due.isoformat()} ({days} day(s) reminder). {nxt.get('explanation', '')}"
    ev = _fire(
        db,
        alert,
        key=f"{alert.id}:earnings:{due.isoformat()}",
        provider="calendar",
        explanation=text,
        observed_time=datetime.now(UTC),
        link=None,
        deactivate=False,
    )
    db.commit()
    return ev


# --------------------------------------------------------------------------- worker cycle
async def run_evaluation_cycle(db: Session, market: MarketDataService, research=None) -> dict:
    """Maintenance, then each active rule against new valid data. Errors in one rule never stop the others."""
    provider = market.source
    now = datetime.now(UTC)
    summary = {"provider": provider, **maintenance(db, now)}
    alerts = [a for a in db.scalars(select(Alert).where(Alert.active.is_(True))) if a.instrument.provider == provider]
    summary.update({"active_alerts": len(alerts), "evaluated": 0, "triggered": 0, "skipped": []})
    by_symbol: dict[str, list[Alert]] = {}
    for a in alerts:
        by_symbol.setdefault(a.instrument.symbol, []).append(a)
    summary["symbols"] = len(by_symbol)

    quote_syms = [s for s, items in by_symbol.items() if any(a.rule in ("PRICE", "CROSS") for a in items)]
    if quote_syms:
        results: dict[str, Result[QuoteSnapshot]] = await market.quotes(quote_syms)
        for sym, r in results.items():
            if r.value is None or r.meta.status not in EVALUABLE_STATUSES:
                reason = r.meta.message or f"Quote {r.meta.status}"
                summary["skipped"].append({"symbol": sym, "status": r.meta.status, "reason": r.meta.message})
                for a in by_symbol[sym]:
                    a.last_skip_reason = f"Not evaluated: {reason}"
                db.commit()
                continue
            inst = by_symbol[sym][0].instrument
            obs = record_observation(db, inst, provider, r.value, r.meta.fetched_at or now)
            for a in by_symbol[sym]:
                if a.rule not in ("PRICE", "CROSS"):
                    continue
                db.refresh(a)
                before = a.last_observation_id
                ev = evaluate_alert(db, a, obs, provider)
                summary["evaluated"] += int(before != obs.id)
                if ev is not None:
                    summary["triggered"] += 1
                    log.info("alert %s triggered", a.id)

    for sym, items in by_symbol.items():
        session_alerts = [a for a in items if a.rule in ("VOLUME", "VOLATILITY")]
        if not session_alerts:
            continue
        hist = await market.history(sym, "3M")
        if hist.value is None or hist.meta.status not in EVALUABLE_STATUSES:
            for a in session_alerts:
                a.last_skip_reason = (
                    f"Not evaluated: daily history {hist.meta.status}. {hist.meta.message or ''}".strip()
                )
            db.commit()
            summary["skipped"].append({"symbol": sym, "status": hist.meta.status, "reason": hist.meta.message})
            continue
        for a in session_alerts:
            summary["evaluated"] += 1
            if evaluate_session_rule(db, a, hist.value.bars, provider, now) is not None:
                summary["triggered"] += 1

    filing_alerts = [a for a in alerts if a.rule == "FILING"]
    for a in filing_alerts:
        if research is None or not research.client.enabled:
            a.last_skip_reason = "Not evaluated: SEC data is not configured."
            db.commit()
            continue
        env = research.filings(db, a.instrument)
        if env.get("status") not in ("available", "cached") or not env.get("data"):
            a.last_skip_reason = f"Not evaluated: filings {env.get('status')}. {env.get('reason') or ''}".strip()
            db.commit()
            continue
        summary["evaluated"] += 1
        summary["triggered"] += len(evaluate_filings(db, a, env["data"]))

    from marketdesk.services.earnings import calendar_for

    today = datetime.now(UTC).date()
    for a in [a for a in alerts if a.rule == "EARNINGS"]:
        try:
            cal = await calendar_for(db, market, research, a.instrument)
        except Exception as exc:  # one listing must not stop the others
            a.last_skip_reason = f"Not evaluated: {type(exc).__name__}"
            db.commit()
            continue
        summary["evaluated"] += 1
        summary["triggered"] += int(evaluate_earnings(db, a, cal, today) is not None)
    return summary

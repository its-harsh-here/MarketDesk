"""Scheduled briefings: a morning note before each session and an end-of-session note after the close, per market.

Timing comes from the exchange calendar (services.sessions), never from weekday/time rules:
- morning: from 90 minutes before the open until the close of a trading day (one per session date);
- close: from 20 minutes after the close, for the most recent closed session, once that session's daily bars exist
  (or, 6 hours after the close, with a coverage note naming the symbols whose bar is still missing).
Days the calendar cannot describe (outside its published data, special sessions) get no briefing.
A briefing is stored once per (kind, market, session date) — the unique key makes generation idempotent across
worker restarts. Content is fixed templates over observed daily bars, alerts and journal review dates: no language
model, no inferred causes, no recommendations.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.models import Alert, AlertEvent, Briefing, Instrument, JournalEntry, Watchlist
from marketdesk.providers.venues import MARKETS
from marketdesk.services import alert_rules as rules
from marketdesk.services.market import MarketDataService
from marketdesk.services.prefs import get_prefs
from marketdesk.services.sessions import CALENDAR_LIBRARY, SPECIAL_SESSIONS, _calendar, calendar_bounds

log = logging.getLogger("marketdesk.briefings")
KINDS = ("morning", "close")
MORNING_LEAD = timedelta(minutes=90)
CLOSE_LAG = timedelta(minutes=20)
CLOSE_DATA_GRACE = timedelta(hours=6)
MAX_SYMBOLS = 30
VOLUME_LOOKBACK, VOLUME_NOTE_MULTIPLE = 20, Decimal("1.5")
USABLE = {"sample", "available", "cached", "stale"}
METHOD = (
    "Fixed rules over completed daily bars, your alerts and journal review dates, timed by the exchange calendar. "
    "No language model is used, no cause is inferred for any move, and nothing here is a recommendation."
)


def market_of(inst: Instrument) -> str | None:
    if inst.country in MARKETS:
        return inst.country
    for code, m in MARKETS.items():
        if inst.timezone == m["timezone"]:
            return code
    return None


def _ts(value) -> datetime:
    return pd.Timestamp(value).tz_convert("UTC").to_pydatetime()


def _describable(code: str, day: date) -> bool:
    first, last = calendar_bounds(MARKETS[code]["calendar"])
    return first <= day <= last and day not in SPECIAL_SESSIONS.get(MARKETS[code]["calendar"], {})


def session_info(code: str, day: date) -> dict | None:
    """Open/close (UTC) of a trading day plus its neighbours, or None if the calendar cannot describe it."""
    cal = _calendar(MARKETS[code]["calendar"])
    if not _describable(code, day) or not cal.is_session(pd.Timestamp(day)):
        return None
    d = pd.Timestamp(day)
    info = {"opens_at": _ts(cal.session_open(d)), "closes_at": _ts(cal.session_close(d))}
    try:
        info["previous_session"] = cal.previous_session(d).date()
    except Exception:  # before the calendar's first session
        info["previous_session"] = None
    try:
        nxt = cal.next_session(d)
        info["next_session"] = nxt.date()
        info["next_opens_at"] = _ts(cal.session_open(nxt))
    except Exception:  # beyond the calendar's published data
        info["next_session"], info["next_opens_at"] = None, None
    info["early_close"] = bool(len(cal.early_closes)) and d in cal.early_closes
    return info


def due_briefings(now: datetime) -> list[tuple[str, str, date, dict]]:
    """(kind, market, session_date, session_info) for each briefing whose time window contains `now`."""
    out = []
    for code, m in MARKETS.items():
        local_day = now.astimezone(ZoneInfo(m["timezone"])).date()
        today = session_info(code, local_day)
        if today and today["opens_at"] - MORNING_LEAD <= now < today["closes_at"]:
            out.append(("morning", code, local_day, today))
        for back in range(0, 8):  # most recent session that has closed
            day = local_day - timedelta(days=back)
            info = session_info(code, day)
            if info is None:
                if not _describable(code, day):
                    break  # no reliable calendar here; never guess
                continue
            if info["closes_at"] + CLOSE_LAG <= now:
                out.append(("close", code, day, info))
                break
    return out


def _fmt_price(v: Decimal | None, ccy: str | None) -> str:
    if v is None:
        return "—"
    prefix = "₹" if ccy == "INR" else ("$" if ccy == "USD" else (f"{ccy} " if ccy else ""))
    return f"{prefix}{v:,.2f}"


def _day(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _fmt_local(dt: datetime | None, tz: str) -> str:
    return "—" if dt is None else dt.astimezone(ZoneInfo(tz)).strftime("%H:%M %Z")


def _instruments(db: Session, code: str, provider: str) -> list[Instrument]:
    """Watchlisted instruments of one market (default watchlist first), plus instruments with active alerts."""
    prefs = get_prefs(db)
    lists = list(db.scalars(select(Watchlist).order_by(Watchlist.position, Watchlist.id)))
    lists.sort(key=lambda w: w.id != prefs["default_watchlist_id"])
    seen: dict[int, Instrument] = {}
    for wl in lists:
        for it in wl.items:
            seen.setdefault(it.instrument.id, it.instrument)
    for a in db.scalars(select(Alert).where(Alert.active.is_(True))):
        seen.setdefault(a.instrument.id, a.instrument)
    picked = [i for i in seen.values() if i.provider == provider and market_of(i) == code]
    return picked[:MAX_SYMBOLS]


def _item(kind: str, tone: str, text: str, detail: str | None = None, symbol: str | None = None) -> dict:
    return {"kind": kind, "tone": tone, "symbol": symbol, "text": text, "detail": detail}


async def generate_briefing(
    db: Session,
    market: MarketDataService,
    kind: str,
    code: str,
    session_date: date,
    info: dict | None = None,
    now: datetime | None = None,
    wait_for_bars: bool = True,
) -> Briefing | None:
    """Build and store one briefing. Returns None if it already exists, has nothing to cover, or its data is not
    ready yet (close briefing before the session's bars are published, within the grace period)."""
    now = now or datetime.now(UTC)
    exists = db.scalar(
        select(Briefing.id).where(Briefing.kind == kind, Briefing.market == code, Briefing.session_date == session_date)
    )
    if exists:
        return None
    m = MARKETS[code]
    tz = m["timezone"]
    info = info if info is not None else (session_info(code, session_date) or {})
    insts = _instruments(db, code, market.source)
    if not insts:
        return None
    items: list[dict] = []
    if kind == "morning" and info.get("opens_at"):
        text = (
            f"{m['name']} trades today ({_day(session_date)}): opens {_fmt_local(info['opens_at'], tz)}, "
            f"closes {_fmt_local(info['closes_at'], tz)}" + (" (early close)." if info.get("early_close") else ".")
        )
        items.append(_item("session", "info", text, f"Exchange calendar: {CALENDAR_LIBRARY}."))
    reference = info.get("previous_session") if kind == "morning" else session_date

    moves, volume_notes, missing, statuses, last_close = [], [], [], set(), {}
    for inst in insts:
        hist = await market.history(inst.symbol, "3M")
        statuses.add(hist.meta.status)
        if hist.value is None or hist.meta.status not in USABLE:
            missing.append(inst.symbol)
            continue
        bars = [b for b in hist.value.bars if b.session_date <= session_date]
        if kind == "morning":
            bars = [b for b in bars if b.session_date < session_date]  # only sessions that have finished
        if kind == "close" and (not bars or bars[-1].session_date != session_date):
            missing.append(inst.symbol)
            continue
        if len(bars) < 2 or bars[-2].close in (None, 0):
            missing.append(inst.symbol)
            continue
        last, prev = bars[-1], bars[-2]
        last_close[inst.id] = last.close
        pct = (last.close / prev.close - 1) * 100
        stale = hist.meta.status == "stale"
        moves.append((pct, inst, last, prev, stale))
        session_d, fired, vtext = rules.volume_signal(bars, VOLUME_LOOKBACK, VOLUME_NOTE_MULTIPLE)
        if session_d is not None and fired:
            volume_notes.append((inst, vtext))

    if kind == "close" and not moves and wait_for_bars and now < (info.get("closes_at") or now) + CLOSE_DATA_GRACE:
        return None  # the session's bars are not published yet; try again next cycle

    moves.sort(key=lambda mv: abs(mv[0]), reverse=True)
    for pct, inst, last, prev, stale in moves[:5]:
        verb = "rose" if pct > 0 else ("fell" if pct < 0 else "was unchanged")
        amount = f" {abs(pct):.2f}%" if pct != 0 else ""
        late = (
            f" (latest available; {_day(reference)} not yet reported)"
            if kind == "morning" and reference and last.session_date != reference
            else ""
        )
        items.append(
            _item(
                "move",
                "positive" if pct > 0 else ("negative" if pct < 0 else "neutral"),
                f"{inst.symbol} {verb}{amount} to {_fmt_price(last.close, inst.currency)} on "
                f"{_day(last.session_date)}{late}" + (" (stale data)." if stale else "."),
                f"Versus previous close {_fmt_price(prev.close, inst.currency)} ({_day(prev.session_date)}); "
                "completed sessions, daily bars.",
                inst.symbol,
            )
        )
    for inst, vtext in volume_notes[:3]:
        items.append(
            _item(
                "volume",
                "info",
                f"{inst.symbol}: {vtext.split(';')[0]}.",
                f"Noted at {rules.plain(VOLUME_NOTE_MULTIPLE)}× or more of the {VOLUME_LOOKBACK}-session average; "
                "completed sessions only. A volume figure, not an explanation of the move.",
                inst.symbol,
            )
        )

    since = info.get("opens_at") if kind == "close" else None
    since = since or now - timedelta(hours=24)
    ids = [i.id for i in insts]
    events = db.execute(
        select(AlertEvent, Alert)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .where(Alert.instrument_id.in_(ids), AlertEvent.triggered_at >= since)
        .order_by(AlertEvent.triggered_at.desc())
        .limit(5)
    ).all()
    for ev, a in events:
        items.append(
            _item("alert", "warning", f"Alert triggered: {a.instrument.symbol}.", ev.explanation, a.instrument.symbol)
        )

    if kind == "morning":
        dist = []
        for a in db.scalars(select(Alert).where(Alert.active.is_(True), Alert.instrument_id.in_(ids))):
            close = last_close.get(a.instrument_id)
            if a.rule in ("PRICE", "CROSS") and close:
                gap = (a.target_price - close) / close * 100
                dist.append((abs(gap), gap, a, close))
        dist.sort(key=lambda d: d[0])
        for _, gap, a, close in dist[:3]:
            ccy = a.instrument.currency
            items.append(
                _item(
                    "threshold",
                    "info",
                    f"{a.instrument.symbol} last closed {abs(gap):.2f}% {'below' if gap > 0 else 'above'} your alert "
                    f"level {_fmt_price(a.target_price, ccy)}.",
                    f"Rule: {a.rule.lower()} {a.direction.lower()}; last close {_fmt_price(close, ccy)}.",
                    a.instrument.symbol,
                )
            )
        reviews = db.scalars(
            select(JournalEntry)
            .where(
                JournalEntry.instrument_id.in_(ids),
                JournalEntry.review_date.is_not(None),
                JournalEntry.review_date <= session_date,
            )
            .order_by(JournalEntry.review_date)
            .limit(3)
        )
        for e in reviews:
            items.append(
                _item(
                    "review",
                    "info",
                    f"Journal review due for {e.instrument.symbol}: “{e.title}”.",
                    f"Review date {_day(e.review_date)}.",
                    e.instrument.symbol,
                )
            )
    elif info.get("next_session"):
        items.append(
            _item(
                "session",
                "info",
                f"Next {m['name']} session: {_day(info['next_session'])}, opens "
                f"{_fmt_local(info['next_opens_at'], tz)}.",
                f"Exchange calendar: {CALENDAR_LIBRARY}.",
            )
        )
    if missing:
        what = f"no completed bar for {_day(session_date)}" if kind == "close" else "no usable daily history"
        items.append(
            _item(
                "coverage",
                "warning",
                f"{len(missing)} of {len(insts)} symbols have {what}: {', '.join(missing[:8])}.",
                "Missing data is left out rather than treated as zero.",
            )
        )

    title = (
        f"{m['name']} morning briefing, {_day(session_date)}"
        if kind == "morning"
        else f"{m['name']} end-of-session briefing, {_day(session_date)}"
    )
    data_status = "sample" if "sample" in statuses else ("stale" if "stale" in statuses else "available")
    content = {
        "title": title,
        "items": items,
        "method": METHOD,
        "data_status": data_status,
        "symbols": len(insts),
        "reference_session": reference.isoformat() if reference else None,
        "session": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in info.items()},
    }
    row = Briefing(
        kind=kind,
        market=code,
        session_date=session_date,
        provider=market.source,
        content=content,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # generated concurrently or by a previous run
        db.rollback()
        return None
    return row


async def run_due_briefings(db: Session, market: MarketDataService, now: datetime | None = None) -> dict:
    if market.source == "fixture":
        # The fixed sample dataset has its own historical dates; pairing it with today's real exchange calendar would
        # mislabel sample bars as recent sessions. Tests use POST /api/fixture/briefing instead.
        return {"generated": [], "note": "Calendar-timed briefings are not generated from the sample dataset."}
    now = now or datetime.now(UTC)
    made = []
    for kind, code, day, info in due_briefings(now):
        try:
            row = await generate_briefing(db, market, kind, code, day, info, now)
        except Exception as exc:  # one market's failure never blocks the other or the alert cycle
            db.rollback()
            log.warning("briefing %s %s %s failed: %s", kind, code, day, type(exc).__name__)
            continue
        if row is not None:
            made.append(f"{kind}:{code}:{day.isoformat()}")
    return {"generated": made}


def briefing_dict(b: Briefing) -> dict:
    c = b.content or {}
    return {
        "id": b.id,
        "kind": b.kind,
        "market": b.market,
        "market_name": MARKETS.get(b.market, {}).get("name", b.market),
        "session_date": b.session_date,
        "provider": b.provider,
        "created_at": b.created_at,
        "read_at": b.read_at,
        "title": c.get("title") or f"{b.kind} briefing",
        "items": c.get("items") or [],
        "method": c.get("method") or METHOD,
        "data_status": c.get("data_status"),
        "reference_session": c.get("reference_session"),
    }

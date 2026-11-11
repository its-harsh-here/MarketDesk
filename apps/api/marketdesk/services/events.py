"""Terminal T4: earnings and corporate events.

A per-security events calendar (past and upcoming) and the same across a declared universe, plus an earnings history
table of reported figures. Every event names its source and whether it is confirmed, estimated or a regulatory
deadline. Nothing here is a consensus estimate: those need licensed data and are reported as such.

Sources used:
- Results: SEC 8-K Item 2.02 filings (US; confirmed past dates; the next date is a cadence estimate) or the SEBI
  LODR 33(3) deadline (India) — via ``earnings.calendar_for``.
- Dividends and splits: the price provider's corporate actions (the action date is taken as the ex-date, as the
  provider reports it).
- Annual meetings (US): DEF 14A proxy statements; the meeting date is quoted from the proxy text when the notice
  states it, otherwise only the filing is shown.
- Buyback announcements (US): sentences mentioning a repurchase programme quoted from recent 8-K press releases
  (a mention, not a confirmed amount).
- Periodic reports (US): 10-K/10-Q filing dates.
Indian exchange announcements (board meetings, AGMs, buybacks) need a permitted source and are not fetched.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from marketdesk.models import Instrument
from marketdesk.providers.base import ProviderError
from marketdesk.services import earnings as er
from marketdesk.services.fin_analysis import _year_before, series
from marketdesk.services.market import MarketDataService

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})", re.IGNORECASE)
_MONTH_INDEX = {name.lower(): i for i, name in enumerate(MONTHS.split("|"), start=1)}
_MEETING = re.compile(
    r"(annual|special)\s+meeting[^.]{0,260}?(?:held|take\s+place|convene)[^.]{0,140}?"
    rf"(({MONTHS})\s+\d{{1,2}},\s+\d{{4}})",
    re.IGNORECASE | re.DOTALL,
)
_BUYBACK = re.compile(r"\b(repurchase|buy-?back)", re.IGNORECASE)
_BUYBACK_CTX = re.compile(r"(program|programme|authoriz|board|\$|million|billion|crore|shares)", re.IGNORECASE)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“])")
EXCLUDED_KINDS = {"INDEX", "CURRENCY"}
PROXY_FORMS = ("DEF 14A",)
RELEASE_FORMS = ("8-K", "8-K/A")
MAX_UNIVERSE = 60
MAX_RELEASES_SCANNED = 8
MAX_CONCURRENT_SCANS = 4


def _today() -> date:
    return datetime.now(UTC).date()


# --------------------------------------------------------------------- pure
def parse_month_date(text: str) -> date | None:
    m = _DATE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), _MONTH_INDEX[m.group(1).lower()], int(m.group(2)))
    except (KeyError, ValueError):
        return None


def meeting_date(text: str, filed: date) -> tuple[date, str, str] | None:
    """The shareholder-meeting date a proxy notice states, the passage it came from and the meeting kind ("annual" or
    "special"). Accepted only when it falls between a week before and 150 days after the filing date (anything else
    is a stray date)."""
    flat = re.sub(r"\s+", " ", text.translate(er._ZERO_WIDTH))
    for m in _MEETING.finditer(flat[:400_000]):
        d = parse_month_date(m.group(2))
        if d and filed - timedelta(days=7) <= d <= filed + timedelta(days=150):
            start = max(0, m.start(2) - 230)
            head = flat[start : m.start(2)]
            cut = head.rfind(". ")  # begin at a sentence boundary when one is within reach
            if cut >= 0 and len(head) - cut < 200:
                head = head[cut + 2 :]
            quote = (head + flat[m.start(2) : m.end() + 40]).strip()
            return d, (quote if len(quote) <= 320 else "…" + quote[-316:]), m.group(1).lower()
    return None


def buyback_sentences(text: str, limit: int = 3) -> list[str]:
    """Sentences in a results release that mention a share repurchase programme (quoted; a mention, not an amount
    verified by MarketDesk)."""
    flat = re.sub(r"\s+", " ", text)
    out: list[str] = []
    for s in _SENT.split(flat):
        if 40 <= len(s) <= 320 and _BUYBACK.search(s) and _BUYBACK_CTX.search(s) and "forward-looking" not in s.lower():
            out.append(s.strip())
            if len(out) >= limit:
                break
    return out


def event(day, kind: str, label: str, status: str, source: str, **extra) -> dict:
    return {"date": day.isoformat() if isinstance(day, date) else day, "kind": kind, "label": label,
            "status": status, "source": source, **extra}  # fmt: skip


def split_events(events: list[dict], today: date) -> dict:
    """Past (newest first) and upcoming (soonest first), without duplicates of the same date, kind and label."""
    seen: set[tuple] = set()
    uniq = []
    for e in events:
        k = (e["date"], e["kind"], e["label"], e.get("symbol"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    past = sorted((e for e in uniq if e["date"] < today.isoformat()), key=lambda e: e["date"], reverse=True)
    upcoming = sorted((e for e in uniq if e["date"] >= today.isoformat()), key=lambda e: e["date"])
    return {"past": past, "upcoming": upcoming}


def yoy(cur: Decimal | None, prev: Decimal | None) -> Decimal | None:
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur / prev - 1) * 100


def history_rows(st: dict, keys=("revenue", "net_income", "eps_diluted")) -> list[dict]:
    """One row per period with the reported figures (value, filed, form, accession) and year-on-year change."""
    ser = {k: series(st, k) for k in keys}
    ends = sorted({e for s in ser.values() for e in s}, reverse=True)
    rows = []
    for end in ends:
        row: dict = {"period_end": end.isoformat(), "start": None}
        for k in keys:
            v = ser[k].get(end)
            if v is None:
                row[k] = None
                continue
            prev_end = _year_before(sorted(ser[k]), end)
            prev = ser[k].get(prev_end) if prev_end else None
            cur = Decimal(str(v["value"]))
            row[k] = {
                "value": cur,
                "unit": v.get("unit"),
                "filed": v.get("filed"),
                "form": v.get("form"),
                "accession": v.get("accession"),
                "url": v.get("source_url"),
                "restated": v.get("restated", False),
                "yoy_pct": yoy(cur, Decimal(str(prev["value"])) if prev else None),
            }
            if v.get("start"):
                row["start"] = v["start"].isoformat() if isinstance(v["start"], date) else v["start"]
        rows.append(row)
    return rows


# --------------------------------------------------------------------- builders
def _sec_on(research) -> bool:
    return research is not None and research.client.enabled


async def _cached_text_features(db: Session, research, specs: list[tuple[str, str, Callable]]) -> list[dict]:
    """For each (cache key, kind, compute) run `compute()` at most once per filing (it fetches and scans a document)
    and keep the result in the market cache. The Session is used from one thread at a time: cache reads first,
    then the misses' fetches and scans concurrently (the SEC client paces its own requests), then the writes."""
    results: list[dict | None] = []
    for key, _, _ in specs:
        payload, _ = await asyncio.to_thread(research._cache_get, db, key)
        results.append(payload)
    missing = [i for i, r in enumerate(results) if r is None]
    gate = asyncio.Semaphore(MAX_CONCURRENT_SCANS)

    async def run(i: int) -> None:
        async with gate:
            results[i] = await specs[i][2]()

    await asyncio.gather(*(run(i) for i in missing))
    for i in missing:
        key, kind, _ = specs[i]
        await asyncio.to_thread(research._cache_put, db, key, kind, results[i])
    return [r or {} for r in results]


def _proxy_spec(research, cik: int, filing: dict) -> tuple[str, str, Callable]:
    """Key v3: the quote window and the meeting kind changed after the first live check."""

    async def compute():
        try:
            text, url = await er._filing_text(research, cik, filing, max_chars=400_000)
        except ProviderError as err:
            return {"error": err.message}
        found = await asyncio.to_thread(meeting_date, text, date.fromisoformat(filing["filing_date"]))
        return {
            "url": url,
            "meeting_date": found[0].isoformat() if found else None,
            "quote": found[1] if found else None,
            "meeting_kind": found[2] if found else None,
        }

    return f"sec:proxy:v3:{filing['accession']}", "sec_proxy", compute


def _release_spec(research, cik: int, filing: dict) -> tuple[str, str, Callable]:
    async def compute():
        try:
            text, url = await er._filing_text(research, cik, filing, max_chars=300_000)
        except ProviderError as err:
            return {"error": err.message, "sentences": []}
        return {"url": url, "sentences": await asyncio.to_thread(buyback_sentences, text)}

    return f"sec:buyback:{filing['accession']}", "sec_buyback", compute


def meeting_label(info: dict) -> str:
    return (
        "Special meeting of shareholders" if info.get("meeting_kind") == "special" else "Annual meeting of shareholders"
    )


def _action_events(acts, source: str) -> list[dict]:
    out = []
    for a in acts or []:
        if a.kind == "DIVIDEND":
            out.append(event(a.action_date, "dividend", f"Dividend {a.value} per share", "confirmed", source,
                             value=str(a.value), detail="Ex-date as reported by the provider."))  # fmt: skip
        elif a.kind == "SPLIT":
            out.append(event(a.action_date, "split", f"Split {a.value}:1", "confirmed", source, value=str(a.value)))
    return out


def _results_events(cal: dict, symbol: str | None = None) -> list[dict]:
    out = []
    for p in cal.get("past") or []:
        out.append(event(p["date"], "results", p["kind"], "confirmed", cal.get("source") or "", url=p.get("url")))
    nxt = cal.get("next")
    if nxt:
        status = "deadline" if nxt.get("basis") == "deadline" else "estimated"
        label = "Results due by (SEBI deadline)" if status == "deadline" else "Next results (estimate)"
        out.append(event(nxt["date"], "results", label, status, cal.get("source") or "", window=nxt.get("window"),
                         detail=nxt.get("explanation")))  # fmt: skip
    for e in out:
        if symbol:
            e["symbol"] = symbol
    return out


async def security_events(db: Session, market: MarketDataService, research, inst: Instrument) -> dict:
    today = _today()
    sources: list[str] = []
    notes: list[str] = []
    events: list[dict] = []
    cal = await er.calendar_for(db, market, research, inst)
    if cal.get("source"):
        sources.append(f"Results: {cal['source']}")
    if cal.get("note") and not cal.get("next"):
        notes.append(cal["note"])
    events += _results_events(cal)
    acts = await market.actions(inst.symbol)
    if acts.value is not None:
        src = f"Dividends and splits: {market.label} corporate actions"
        sources.append(src)
        events += _action_events(acts.value, f"{market.label} corporate actions")
    elif acts.meta.message:
        notes.append(f"Corporate actions: {acts.meta.message}")
    if inst.country == "US" and _sec_on(research):
        env = await asyncio.to_thread(research.filings, db, inst, 80)
        rows = env.get("data") or []
        cik = env.get("cik")
        sources.append("Filings, meetings and buyback mentions: SEC EDGAR")
        for r in rows:
            if r["form"] in ("10-K", "10-Q", "20-F", "40-F"):
                events.append(event(r["filing_date"], "report", f"{r['form']} filed", "confirmed", "SEC EDGAR",
                                    url=r.get("document_url") or r.get("index_url"),
                                    period=r.get("report_date")))  # fmt: skip
        proxies = [r for r in rows if r["form"] in PROXY_FORMS][:2]
        releases = [r for r in rows if r["form"] in RELEASE_FORMS and "2.02" in (r.get("items") or [])]
        releases = releases[:MAX_RELEASES_SCANNED]
        scans = await _cached_text_features(
            db,
            research,
            [_proxy_spec(research, cik, r) for r in proxies] + [_release_spec(research, cik, r) for r in releases],
        )
        proxy_info, release_info = scans[: len(proxies)], scans[len(proxies) :]
        for r, info in zip(proxies, proxy_info, strict=True):
            events.append(event(r["filing_date"], "proxy", "Proxy statement filed (DEF 14A)", "confirmed", "SEC EDGAR",
                                url=info.get("url") or r.get("document_url") or r.get("index_url")))  # fmt: skip
            if info.get("meeting_date"):
                events.append(event(info["meeting_date"], "meeting", meeting_label(info), "confirmed",
                                    "SEC EDGAR · quoted from the proxy statement", url=info.get("url"),
                                    quote=info.get("quote")))  # fmt: skip
            elif info.get("error"):
                notes.append(f"Proxy filed {r['filing_date']}: could not be read ({info['error']}).")
            else:
                notes.append(f"Proxy filed {r['filing_date']}: no meeting date stated in a recognisable form.")
        for r, info in zip(releases, release_info, strict=True):
            for s in info.get("sentences") or []:
                events.append(event(r["filing_date"], "buyback", "Share repurchase mentioned in results release",
                                    "mention", "SEC EDGAR · quoted from the release", url=info.get("url"),
                                    quote=s))  # fmt: skip
    elif inst.country == "US":
        notes.append("SEC data is not configured on this server: filings, meetings and buybacks are not shown.")
    elif er.is_india(inst):
        notes.append(
            "Board meetings, AGMs and buyback announcements for Indian listings need a permitted exchange source "
            "(BSE licence or verified NSE terms) and are not shown."
        )
    out = split_events(events, today)
    return {
        "symbol": inst.symbol,
        "as_of": today.isoformat(),
        **out,
        "sources": sources,
        "notes": notes,
        "consensus": {
            "status": "licensed",
            "reason": "Consensus estimates and earnings surprises are licensed data; shown only with a provider that "
            "permits personal use.",
        },
    }


async def universe_events(db: Session, market: MarketDataService, research, spec: dict, ahead: int, back: int) -> dict:
    from marketdesk.services.screener import resolve_universe

    today = _today()
    lo, hi = today - timedelta(days=back), today + timedelta(days=ahead)
    uni = resolve_universe(db, market.source, spec, 500)
    insts = [i for i in uni["instruments"] if (i.kind or "").upper() not in EXCLUDED_KINDS]
    events: list[dict] = []
    failed: list[str] = []
    for inst in insts[:MAX_UNIVERSE]:
        try:
            cal = await er.calendar_for(db, market, research, inst)
            events += _results_events(cal, inst.symbol)
            acts = await market.actions(inst.symbol)
            for e in _action_events(acts.value, f"{market.label} corporate actions"):
                events.append({**e, "symbol": inst.symbol})
            if inst.country == "US" and _sec_on(research):
                env = await asyncio.to_thread(research.filings, db, inst, 80)
                for r in env.get("data") or []:
                    if r["form"] in PROXY_FORMS and lo.isoformat() <= r["filing_date"] <= hi.isoformat():
                        info, _ = await asyncio.to_thread(research._cache_get, db, f"sec:proxy:v3:{r['accession']}")
                        events.append({**event(r["filing_date"], "proxy", "Proxy statement filed (DEF 14A)",
                                               "confirmed", "SEC EDGAR",
                                               url=r.get("document_url") or r.get("index_url")),
                                       "symbol": inst.symbol})  # fmt: skip
                        if info and info.get("meeting_date"):
                            events.append({**event(info["meeting_date"], "meeting", meeting_label(info),
                                                   "confirmed", "SEC EDGAR · quoted from the proxy statement",
                                                   url=info.get("url")), "symbol": inst.symbol})  # fmt: skip
        except Exception as exc:  # one listing's failure must not hide the others
            failed.append(f"{inst.symbol}: {type(exc).__name__}")
    windowed = [e for e in events if lo.isoformat() <= e["date"] <= hi.isoformat()]
    out = split_events(windowed, today)
    return {
        "universe": {"label": uni["label"], "members": len(insts), "scanned": min(len(insts), MAX_UNIVERSE)},
        "window": {"from": lo.isoformat(), "to": hi.isoformat(), "ahead_days": ahead, "back_days": back},
        **out,
        "failed": failed,
        "note": "Results dates are confirmed past filings (US), cadence estimates (US) or SEBI deadlines (India); "
        "dividends and splits are the provider's past actions; meetings come from proxy statements already read on an "
        "instrument's Events tab. No consensus figures.",
    }


async def earnings_history(db: Session, market: MarketDataService, research, inst: Instrument) -> dict:
    base = {"symbol": inst.symbol, "consensus": {"status": "licensed",
            "reason": "Estimates and surprises need licensed data; only reported figures are shown."}}  # fmt: skip
    if inst.country == "US" and _sec_on(research):
        env = await asyncio.to_thread(research.financials, db, inst, "quarterly", None, None, None, 12)
        st = env.get("data")
        if st and st.get("period_ends"):
            return {**base, "status": env["status"], "period": "quarterly", "official": True,
                    "currency": st.get("currency"), "source": "SEC EDGAR company facts (three-month durations)",
                    "rows": history_rows(st), "fetched_at": env.get("fetched_at")}  # fmt: skip
        if env.get("status") != "not_applicable":
            return {**base, "status": env.get("status"), "reason": env.get("reason") or "No quarterly SEC facts."}
    r = await market.statements(inst.symbol)
    if r.value is None or not r.value.periods:
        return {
            **base,
            "status": "missing",
            "reason": r.meta.message or "The provider has no statements for this listing.",
        }
    st = {
        "period": "annual",
        "period_ends": [p.period_end for p in r.value.periods],
        "lines": [
            {
                "key": k,
                "values": [
                    {
                        "value": getattr(p, k),
                        "unit": "statement currency",
                        "end": p.period_end,
                        "start": None,
                        "form": r.value.source,
                        "filed": None,
                        "accession": None,
                        "prior": [],
                        "restated": False,
                    }
                    for p in r.value.periods
                    if getattr(p, k) is not None
                ],
            }  # fmt: skip
            for k in ("revenue", "net_income")
        ],
    }
    return {**base, "status": r.meta.status, "period": "annual", "official": False, "currency": None,
            "source": f"{r.value.source} (unofficial provider data; annual only)",
            "rows": history_rows(st, ("revenue", "net_income")),
            "fetched_at": r.meta.fetched_at.isoformat() if r.meta.fetched_at else None,
            "notes": ["Quarterly reported figures need SEC company facts (US registrants); this listing has annual "
                      "provider statements only."]}  # fmt: skip


def jsonable(x):
    if isinstance(x, Decimal):
        return format(x.quantize(Decimal("0.0001")), "f")
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    return x

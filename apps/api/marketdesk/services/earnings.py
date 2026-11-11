"""Earnings and filing analysis (M07).

- Calendar: past results dates come from filings (US: SEC 8-K Item 2.02). A next date is never presented as
  announced: for US listings it is an *estimate* from the cadence of past results filings; for Indian listings it is
  the regulatory *deadline* (SEBI LODR Regulation 33(3): quarterly results within 45 days of the quarter end, annual
  results within 60 days of the financial year end). No consensus estimates are used or invented.
- Period changes: quarter-on-quarter and year-on-year from SEC quarterly facts (quarterly durations only, never
  year-to-date), fiscal-year changes from annual facts or the provider's annual statements; restated values are
  marked; every input links to its filing.
- Filing changes: paragraphs of the risk-factor section added, removed or reworded between two filings of the same
  form, quoted from the filings themselves. Guidance: sentences quoted from results releases. Nothing is paraphrased.
"""

from __future__ import annotations

import asyncio
import difflib
import re
import statistics
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from marketdesk.models import Instrument
from marketdesk.providers.base import ProviderError
from marketdesk.services.market import MarketDataService

USABLE = {"sample", "available", "cached", "stale"}
SEBI_RULE = (
    "SEBI LODR Regulation 33(3): quarterly results within 45 days of the quarter end; annual results within 60 days of "
    "the financial year end. This is the latest permitted date, not an announced one — companies announce their board "
    "meeting dates on the exchanges."
)
RESULT_FORMS = ("8-K", "8-K/A")
_CACHE: OrderedDict[str, dict] = OrderedDict()


def _cache_get(key: str) -> dict | None:
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def _cache_put(key: str, value: dict) -> None:
    _CACHE[key] = value
    while len(_CACHE) > 24:
        _CACHE.popitem(last=False)


def is_india(inst: Instrument) -> bool:
    return inst.country == "IN" or (inst.country is None and inst.timezone == "Asia/Kolkata")


def _today() -> date:
    return datetime.now(UTC).date()


# --------------------------------------------------------------------- calendar
def cadence_estimate(result_dates: list[date], today: date) -> dict | None:
    """Next results date estimated from the median gap of past results dates (needs three or more, quarterly-like)."""
    ds = sorted(set(result_dates))
    if len(ds) < 3:
        return None
    gaps = [(b - a).days for a, b in zip(ds, ds[1:], strict=False)]
    gap = int(statistics.median(gaps))
    if not 60 <= gap <= 120:
        return None
    nxt = ds[-1] + timedelta(days=gap)
    while nxt + timedelta(days=7) < today:
        nxt += timedelta(days=gap)
    return {
        "date": nxt.isoformat(),
        "window": [(nxt - timedelta(days=7)).isoformat(), (nxt + timedelta(days=7)).isoformat()],
        "basis": "estimated",
        "explanation": f"Estimated from the median gap ({gap} days) between the last {len(ds)} results filings "
        "(SEC 8-K Item 2.02); not announced by the company. The window is ±7 days.",
    }


def quarter_end_after(d: date) -> date:
    nxt = d + relativedelta(months=3)
    return (nxt.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)


def sebi_deadline(last_quarter: date, fy_end: date | None, today: date) -> dict:
    """Deadline for the first quarter after `last_quarter` whose deadline is not in the past."""
    q = quarter_end_after(last_quarter)
    while True:
        annual = fy_end is not None and q.month == fy_end.month
        due = q + timedelta(days=60 if annual else 45)
        if due >= today:
            break
        q = quarter_end_after(q)
    return {
        "date": due.isoformat(),
        "window": None,
        "basis": "deadline",
        "period_end": q.isoformat(),
        "period": "financial year" if annual else "quarter",
        "explanation": SEBI_RULE,
    }


async def calendar_for(db: Session, market: MarketDataService, research, inst: Instrument) -> dict:
    out: dict = {"symbol": inst.symbol, "name": inst.name, "past": [], "next": None, "source": None, "note": None}
    today = _today()
    if inst.country == "US" and research is not None and research.client.enabled:
        env = await asyncio.to_thread(research.filings, db, inst, 80)
        rows = env.get("data") or []
        res = [r for r in rows if r["form"] in RESULT_FORMS and "2.02" in (r.get("items") or [])]
        out["past"] = [
            {
                "date": r["filing_date"],
                "kind": "Results (8-K Item 2.02)",
                "url": r.get("document_url") or r.get("index_url"),
            }
            for r in res[:8]
        ]
        out["source"] = "SEC EDGAR filings"
        out["next"] = cadence_estimate([date.fromisoformat(r["filing_date"]) for r in res], today)
        if out["next"] is None:
            out["note"] = (
                "Too few regular results filings to estimate the next date."
                if env.get("data") is not None
                else env.get("reason")
            )
        return out
    if is_india(inst):
        f = await market.fundamentals(inst.symbol)
        fv = f.value if f.value is not None and f.meta.status in USABLE else None
        if fv and fv.most_recent_quarter:
            out["past"] = [
                {"date": fv.most_recent_quarter.isoformat(), "kind": "Latest reported quarter end", "url": None}
            ]
            out["next"] = sebi_deadline(fv.most_recent_quarter, fv.last_fiscal_year_end, today)
            out["source"] = f"{market.label} fundamentals (latest reported quarter) + SEBI rule"
        else:
            out["note"] = "The provider does not report the latest quarter for this listing."
        return out
    out["note"] = (
        "Results dates come from SEC filings (US registrants) or the SEBI deadline (Indian listings); neither applies "
        "here."
        if inst.country != "US"
        else "SEC data is not configured on this server."
    )
    return out


# --------------------------------------------------------------------- period changes
LINES = ("revenue", "gross_profit", "operating_income", "net_income", "long_term_debt", "equity", "operating_cash_flow")


def _pct(a: Decimal | None, b: Decimal | None) -> str | None:
    if a is None or b is None or b == 0:
        return None
    return format(((a - b) / abs(b) * 100).quantize(Decimal("0.01")), "f")


def compare_periods(st: dict, mode: str) -> list[dict]:
    """Rows of (latest, comparison, change) per line, from a research envelope's statements (ISO dates, decimal
    strings). mode: 'qoq' (previous quarter), 'yoy' (same quarter a year earlier, ±20 days) or 'fy' (previous fiscal
    year). Only values of the statement's own period type exist there, so quarters and year-to-date never mix."""
    ends = [date.fromisoformat(str(e)[:10]) for e in st.get("period_ends") or []]
    if not ends:
        return []
    latest = ends[0]
    if mode == "qoq":
        prior = ends[1] if len(ends) > 1 else None
    else:
        target = latest - relativedelta(years=1)
        prior = next((e for e in ends[1:] if abs((e - target).days) <= 20), None)
    rows = []
    for line in st.get("lines") or []:
        if line["key"] not in LINES or line.get("status") != "available":
            continue
        by_end = {str(v["end"])[:10]: v for v in line["values"]}
        a = by_end.get(latest.isoformat())
        b = by_end.get(prior.isoformat()) if prior else None
        rows.append(
            {
                "key": line["key"],
                "label": line["label"],
                "latest": _fv(a),
                "prior": _fv(b),
                "change_pct": _pct(Decimal(a["value"]) if a else None, Decimal(b["value"]) if b else None),
            }
        )
    by_key = {r["key"]: r for r in rows}

    def margin(num: str, side: str) -> Decimal | None:
        n, d = (by_key.get(num) or {}).get(side), (by_key.get("revenue") or {}).get(side)
        if not n or not d or Decimal(d["value"]) == 0:
            return None
        return Decimal(n["value"]) / Decimal(d["value"]) * 100

    for name, num in (
        ("gross_margin", "gross_profit"),
        ("operating_margin", "operating_income"),
        ("net_margin", "net_income"),
    ):
        ma, mb = margin(num, "latest"), margin(num, "prior")
        if ma is None and mb is None:
            continue
        rows.append(
            {
                "key": name,
                "label": name.replace("_", " ").capitalize(),
                "latest": None,
                "prior": None,
                "change_pct": None,
                "latest_pct": None if ma is None else format(ma.quantize(Decimal("0.01")), "f"),
                "prior_pct": None if mb is None else format(mb.quantize(Decimal("0.01")), "f"),
                "change_pp": None if ma is None or mb is None else format((ma - mb).quantize(Decimal("0.01")), "f"),
            }
        )
    return [
        {"mode": mode, "latest_end": latest.isoformat(), "prior_end": prior.isoformat() if prior else None, **r}
        for r in rows
    ]


def _fv(v: dict | None) -> dict | None:
    if v is None:
        return None
    return {
        k: v.get(k) for k in ("value", "unit", "start", "end", "form", "filed", "accession", "restated", "source_url")
    } | {"prior": v.get("prior") or []}


def annual_changes(periods: list) -> list[dict]:
    """Fiscal-year changes from the provider's annual statements (non-SEC listings)."""
    if len(periods) < 2:
        return []
    p0, p1 = periods[0], periods[1]
    rows = []
    for key, label in (
        ("revenue", "Revenue"),
        ("net_income", "Net income"),
        ("operating_cash_flow", "Operating cash flow"),
        ("total_debt", "Total debt"),
        ("total_equity", "Shareholders' equity"),
    ):
        a, b = getattr(p0, key), getattr(p1, key)
        rows.append(
            {
                "key": key,
                "label": label,
                "latest": None if a is None else {"value": str(a), "end": p0.period_end.isoformat()},
                "prior": None if b is None else {"value": str(b), "end": p1.period_end.isoformat()},
                "change_pct": _pct(a, b),
            }
        )
    return [
        {"mode": "fy", "latest_end": p0.period_end.isoformat(), "prior_end": p1.period_end.isoformat(), **r}
        for r in rows
    ]


# --------------------------------------------------------------------- filing changes
_RISK_HEAD = re.compile(r"item\s*1a\.?\s*[\-–—:]?\s*risk\s+factors", re.IGNORECASE)
_NEXT_HEAD = re.compile(
    r"item\s*(1b|1c|2)\.?\s*[\-–—:]?\s*(unresolved|cybersecurity|properties|unregistered|management)", re.IGNORECASE
)


_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
_RISK_ANY = re.compile(r"risk\s+factors", re.IGNORECASE)


def _section_after(text: str, start: int) -> str:
    tail = text[start:]
    stop = _NEXT_HEAD.search(tail)
    return tail[: stop.start()] if stop else tail[:200_000]


def risk_section(text: str) -> str | None:
    """The longest 'Item 1A. Risk Factors' section (the table of contents entry is short). Falls back to the longest
    text following any 'Risk Factors' heading when the item number is formatted unusually."""
    text = text.translate(_ZERO_WIDTH)
    best = None
    for m in _RISK_HEAD.finditer(text):
        body = _section_after(text, m.end())
        if best is None or len(body) > len(best):
            best = body
    if not best or len(best) <= 200:
        for m in _RISK_ANY.finditer(text):
            body = _section_after(text, m.end())
            if best is None or len(body) > len(best):
                best = body
    return best if best and len(best) > 200 else None


def risk_diagnostics(text: str) -> dict:
    t = text.translate(_ZERO_WIDTH)
    first = _RISK_ANY.search(t)
    return {
        "chars": len(t),
        "item_1a_headings": len(_RISK_HEAD.findall(t)),
        "risk_factor_mentions": len(_RISK_ANY.findall(t)),
        "item_1a_mentions": len(re.findall(r"item\s*1a", t, re.IGNORECASE)),
        "sample": t[max(0, first.start() - 60) : first.start() + 60] if first else t[:120],
    }


def paragraphs(section: str) -> list[str]:
    parts = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n+", section)]
    return [p for p in parts if len(p) >= 80]


def _norm(p: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", p.lower())


MAX_COMPARE = 400  # paragraphs per side considered for rewording (a 10-K's Item 1A has roughly 100-300)


def _bigrams(words: list[str]) -> set[tuple[str, str]]:
    return set(zip(words, words[1:], strict=False))


def diff_paragraphs(old: list[str], new: list[str], limit: int = 12) -> dict:
    """Added, removed and reworded paragraphs (similarity ≥ 0.6 counts as reworded), quoted.

    Rewording is found in two steps so that whole annual reports stay fast: a cheap word-pair (bigram) overlap picks
    the three closest removed paragraphs for each added one, and only those are compared word by word with
    difflib. Character-level comparison of every pair was quadratic and took minutes on real 10-K sections."""
    old_n = {_norm(p): p for p in old}
    new_n = {_norm(p): p for p in new}
    added = [k for k in new_n if k not in old_n]
    removed = [k for k in old_n if k not in new_n]
    words = {k: k.split() for k in (*added[:MAX_COMPARE], *removed[:MAX_COMPARE])}
    grams = {k: _bigrams(w) for k, w in words.items()}
    reworded, used = [], set()
    for k in list(added[:MAX_COMPARE]):
        gk = grams[k]
        if not gk:
            continue
        shortlist = []
        for r in removed[:MAX_COMPARE]:
            if r in used or not grams[r]:
                continue
            j = len(gk & grams[r]) / len(gk | grams[r])
            if j >= 0.2:
                shortlist.append((j, r))
        best, score = None, 0.0
        for _, r in sorted(shortlist, reverse=True)[:3]:
            s = difflib.SequenceMatcher(None, words[k], words[r], autojunk=False).ratio()
            if s > score:
                best, score = r, s
        if best is not None and score >= 0.6:
            reworded.append((best, k, score))
            used.add(best)
            added.remove(k)
    removed = [r for r in removed if r not in used]

    def cut(p: str) -> str:
        return p if len(p) <= 700 else p[:697].rstrip() + "…"

    return {
        "counts": {
            "old": len(old),
            "new": len(new),
            "added": len(added),
            "removed": len(removed),
            "reworded": len(reworded),
        },
        "added": [cut(new_n[k]) for k in added[:limit]],
        "removed": [cut(old_n[k]) for k in removed[:limit]],
        "reworded": [
            {"before": cut(old_n[a]), "after": cut(new_n[b]), "similarity": round(s, 2)} for a, b, s in reworded[:limit]
        ],
    }


async def _filing_text(research, cik: int, filing: dict, max_chars: int = 2_000_000) -> tuple[str, str]:
    from marketdesk.services.analyst import _pick_document

    client = research.client
    files = await asyncio.to_thread(client.filing_files, cik, filing["accession"])
    doc = _pick_document(files, filing["form"], filing)
    if doc is None:
        raise ProviderError("missing", "No readable document in this filing.")
    text = await asyncio.to_thread(client.document_text, cik, filing["accession"], doc, max_chars, 20_000_000)
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{filing['accession'].replace('-', '')}/{doc}"
    return text, url


async def filing_changes(db: Session, research, inst: Instrument, form: str) -> dict:
    if inst.country != "US" or research is None or not research.client.enabled:
        return {
            "available": False,
            "reason": "Filing comparisons use SEC filings (US registrants with SEC data configured).",
        }
    env = await asyncio.to_thread(research.filings, db, inst, 80)
    rows = [r for r in (env.get("data") or []) if r["form"] == form]
    if len(rows) < 2:
        return {"available": False, "reason": f"Fewer than two {form} filings are listed for this company."}
    new_f, old_f = rows[0], rows[1]
    key = f"risk:{new_f['accession']}:{old_f['accession']}"
    if (hit := _cache_get(key)) is not None:
        return hit
    cik = env.get("cik")
    try:
        (new_t, new_url), (old_t, old_url) = await asyncio.gather(
            _filing_text(research, cik, new_f), _filing_text(research, cik, old_f)
        )
    except ProviderError as err:
        return {"available": False, "reason": f"Could not read the filings: {err.message}"}
    ns, os_ = await asyncio.gather(asyncio.to_thread(risk_section, new_t), asyncio.to_thread(risk_section, old_t))
    if not ns or not os_:
        return {
            "available": False,
            "reason": "A risk-factor section (Item 1A) was not found in one of the filings.",
            "filings": [
                {
                    "form": f["form"],
                    "filing_date": f["filing_date"],
                    "url": u,
                    "found": bool(sec),
                    "diagnostics": None if sec else risk_diagnostics(t),
                }
                for f, u, t, sec in ((new_f, new_url, new_t, ns), (old_f, old_url, old_t, os_))
            ],
        }
    out = {
        "available": True,
        "section": "Item 1A. Risk Factors",
        "new": {
            "form": new_f["form"],
            "filing_date": new_f["filing_date"],
            "report_date": new_f.get("report_date"),
            "url": new_url,
        },
        "old": {
            "form": old_f["form"],
            "filing_date": old_f["filing_date"],
            "report_date": old_f.get("report_date"),
            "url": old_url,
        },
        **(await asyncio.to_thread(lambda: diff_paragraphs(paragraphs(os_), paragraphs(ns)))),
        "method": "Paragraphs (80+ characters) of each filing's Item 1A are compared after normalizing case and "
        "punctuation; pairs at least 60% similar word by word count as reworded. All text is quoted from the filings.",
    }
    _cache_put(key, out)
    return out


_GUIDE = re.compile(
    r"\b(guidance|outlook|expects?|expected|anticipates?|forecasts?|reaffirm\w*|raises?|lowers?)\b", re.IGNORECASE
)


def guidance_sentences(text: str, limit: int = 6) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", re.sub(r"\s+", " ", text))
    out = []
    for s in sents:
        if 40 <= len(s) <= 600 and _GUIDE.search(s) and re.search(r"\d", s) and "forward-looking" not in s.lower():
            out.append(s.strip())
        if len(out) >= limit:
            break
    return out


async def guidance(db: Session, research, inst: Instrument, releases: int = 4) -> dict:
    if inst.country != "US" or research is None or not research.client.enabled:
        return {"available": False, "reason": "Guidance quotes come from US results releases (SEC 8-K exhibits)."}
    env = await asyncio.to_thread(research.filings, db, inst, 80)
    res = [r for r in (env.get("data") or []) if r["form"] in RESULT_FORMS and "2.02" in (r.get("items") or [])][
        :releases
    ]
    if not res:
        return {"available": False, "reason": "No results releases (8-K Item 2.02) are listed."}
    key = "guide:" + ":".join(r["accession"] for r in res)
    if (hit := _cache_get(key)) is not None:
        return hit
    timeline = []
    for r in res:
        try:
            text, url = await _filing_text(research, env.get("cik"), r, 300_000)
        except ProviderError as err:
            timeline.append(
                {"filing_date": r["filing_date"], "url": r.get("index_url"), "quotes": [], "error": err.message}
            )
            continue
        timeline.append({"filing_date": r["filing_date"], "url": url, "quotes": guidance_sentences(text)})
    out = {
        "available": True,
        "timeline": timeline,
        "method": "Sentences that mention guidance, outlook or expectations and contain a figure, quoted from each "
        "results release (exhibit 99); forward-looking-statement boilerplate is skipped. Not interpreted.",
    }
    _cache_put(key, out)
    return out


async def period_changes(db: Session, market: MarketDataService, research, inst: Instrument) -> dict:
    if inst.country == "US" and research is not None and research.client.enabled:
        q = await asyncio.to_thread(research.financials, db, inst, "quarterly")
        a = await asyncio.to_thread(research.financials, db, inst, "annual")
        if q.get("data") or a.get("data"):
            qd, ad = q.get("data") or {}, a.get("data") or {}
            return {
                "available": True,
                "source": "SEC company facts (XBRL)",
                "currency": qd.get("currency") or ad.get("currency"),
                "qoq": compare_periods(qd, "qoq") if qd else [],
                "yoy": compare_periods(qd, "yoy") if qd else [],
                "fy": compare_periods(ad, "fy") if ad else [],
                "note": "Quarterly figures are three-month durations only (never year-to-date); annual figures are "
                "fiscal years. Restated values are marked and earlier filings' values are listed.",
            }
    st = await market.statements(inst.symbol)
    if st.value is None or st.meta.status not in USABLE:
        return {
            "available": False,
            "reason": st.meta.message or "No reported statements are available for this listing.",
        }
    return {
        "available": True,
        "source": st.value.source,
        "currency": None,
        "qoq": [],
        "yoy": [],
        "fy": annual_changes(st.value.periods),
        "note": "Fiscal-year changes from the provider's annual statements (statement currency not stated by the "
        "provider; changes are ratios). Quarterly comparisons need SEC data (US registrants).",
    }


async def universe_calendar(db: Session, market: MarketDataService, research, max_size: int = 40) -> dict:
    from sqlalchemy import select

    from marketdesk.models import Alert
    from marketdesk.services.screener import EXCLUDED_KINDS, tracked_instruments

    tracked = {i.id: i for i in tracked_instruments(db, market.source, 150)}
    for a in db.scalars(select(Alert).where(Alert.active.is_(True))):
        if a.instrument.provider == market.source:
            tracked.setdefault(a.instrument.id, a.instrument)
    insts = [i for i in tracked.values() if (i.kind or "").upper() not in EXCLUDED_KINDS]
    rows = []
    for inst in insts[:max_size]:
        try:
            rows.append(await calendar_for(db, market, research, inst))
        except Exception as exc:  # one listing's failure must not hide the others
            rows.append(
                {"symbol": inst.symbol, "name": inst.name, "past": [], "next": None, "note": type(exc).__name__}
            )
    rows.sort(key=lambda r: ((r.get("next") or {}).get("date") or "9999", r["symbol"]))
    return {
        "rows": rows,
        "truncated": max(0, len(insts) - max_size),
        "universe": "Watchlists, holdings, lists, peers and alerts",
        "note": "Next dates are estimates (US: cadence of past SEC results filings) or deadlines (India: SEBI); "
        "none is an announced date, and no consensus figures are used.",
    }

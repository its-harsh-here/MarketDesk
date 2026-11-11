"""Terminal T3: ownership and insiders.

US insider transactions come from the Form 4 XML each insider files (SEC EDGAR, via the issuer's submissions):
who, their role, the transaction code in words, shares, price, and holdings after. The ownership breakdown and the
largest institutional and fund holders come from the price provider (Yahoo, unofficial; for India this is Yahoo's
summary, not the exchange shareholding pattern, which needs a permitted source — promoter and pledge data stay
off until then).
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET  # noqa: S405 - expat ≥2.4 limits entity expansion; DOCTYPEs are refused upstream
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from marketdesk.models import Instrument
from marketdesk.providers.base import ProviderError
from marketdesk.services import earnings as er
from marketdesk.services.market import MarketDataService

# SEC Form 4 General Instructions, transaction codes (Table I and II), in plain words.
CODES = {
    "P": "Open-market purchase",
    "S": "Open-market sale",
    "A": "Grant or award",
    "D": "Disposition to the issuer",
    "F": "Shares withheld for tax or exercise price",
    "I": "Discretionary transaction",
    "M": "Option or derivative exercise",
    "C": "Conversion of a derivative",
    "E": "Expiration of a short derivative position",
    "H": "Expiration of a long derivative position",
    "O": "Exercise of an out-of-the-money derivative",
    "X": "Exercise of an in-the-money derivative",
    "G": "Gift",
    "L": "Small acquisition",
    "W": "Acquired or disposed of by will or inheritance",
    "Z": "Deposit into or withdrawal from a voting trust",
    "J": "Other acquisition or disposition",
    "K": "Equity swap or similar",
    "U": "Disposition in a change-of-control tender",
    "V": "Voluntarily reported transaction",
}
MAX_FILINGS = 25
MAX_CONCURRENT = 4


def _t(node, path: str) -> str | None:
    el = node.find(path) if node is not None else None
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def _num(node, path: str) -> Decimal | None:
    v = _t(node, path)
    try:
        return Decimal(v) if v is not None else None
    except InvalidOperation:
        return None


def parse_form4(xml_text: str) -> dict:
    """Owners, roles and non-derivative transactions of one Form 4 ownership document."""
    root = ET.fromstring(xml_text)  # noqa: S314 - see the import note
    owners = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        roles = []
        if _t(rel, "isDirector") in ("1", "true"):
            roles.append("Director")
        if _t(rel, "isOfficer") in ("1", "true"):
            roles.append(_t(rel, "officerTitle") or "Officer")
        if _t(rel, "isTenPercentOwner") in ("1", "true"):
            roles.append("10% owner")
        if _t(rel, "isOther") in ("1", "true"):
            roles.append(_t(rel, "otherText") or "Other")
        owners.append({"name": _t(ro, "reportingOwnerId/rptOwnerName") or "Unknown", "roles": roles})
    txns = []
    for tr in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _t(tr, "transactionCoding/transactionCode")
        shares = _num(tr, "transactionAmounts/transactionShares/value")
        price = _num(tr, "transactionAmounts/transactionPricePerShare/value")
        ad = _t(tr, "transactionAmounts/transactionAcquiredDisposedCode/value")
        txns.append({
            "date": _t(tr, "transactionDate/value"),
            "security": _t(tr, "securityTitle/value"),
            "code": code,
            "action": CODES.get(code or "", f"Code {code}" if code else "Not stated"),
            "acquired": ad == "A" if ad in ("A", "D") else None,
            "shares": shares,
            "price": price,
            "value": (shares * price) if shares is not None and price is not None and price > 0 else None,
            "owned_after": _num(tr, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
            "direct": _t(tr, "ownershipNature/directOrIndirectOwnership/value") != "I",
            "plan_10b5_1": _t(root, "aff10b5One") in ("1", "true"),
        })  # fmt: skip
    return {"owners": owners, "transactions": txns, "period": _t(root, "periodOfReport")}


def summarize(rows: list[dict], today: date, days: int) -> dict:
    """Open-market buys (P) and sales (S) in the last `days`: counts, shares, value, distinct insiders."""
    since = (today - timedelta(days=days)).isoformat()
    window = [r for r in rows if (r.get("date") or "") >= since]
    out = {"days": days}
    for key, code in (("buys", "P"), ("sales", "S")):
        sel = [r for r in window if r.get("code") == code]
        out[key] = {
            "count": len(sel),
            "shares": sum((r["shares"] for r in sel if r.get("shares") is not None), Decimal(0)),
            "value": sum((r["value"] for r in sel if r.get("value") is not None), Decimal(0)),
            "insiders": len({r["insider"] for r in sel}),
        }
    return out


async def _cached_many(db: Session, research, specs: list[tuple[str, Callable]]) -> list[dict]:
    """Cache reads, then at most MAX_CONCURRENT fetches, then cache writes — the Session on one thread at a time."""
    results: list[dict | None] = []
    for key, _ in specs:
        payload, _ = await asyncio.to_thread(research._cache_get, db, key)
        results.append(payload)
    missing = [i for i, r in enumerate(results) if r is None]
    gate = asyncio.Semaphore(MAX_CONCURRENT)

    async def run(i: int) -> None:
        async with gate:
            results[i] = await specs[i][1]()

    await asyncio.gather(*(run(i) for i in missing))
    for i in missing:
        await asyncio.to_thread(research._cache_put, db, specs[i][0], "sec_form4", results[i])
    return [r or {} for r in results]


def _jsonable_form4(parsed: dict) -> dict:
    def conv(v):
        return format(v, "f") if isinstance(v, Decimal) else v

    return {**parsed, "transactions": [{k: conv(v) for k, v in t.items()} for t in parsed["transactions"]]}


async def insiders(db: Session, research, inst: Instrument, today: date) -> dict:
    base = {"source": "SEC EDGAR Form 4 (insider ownership reports)"}
    if inst.country != "US":
        return {**base, "status": "not_applicable", "reason": "Form 4 covers insiders of US-registered issuers."}
    if research is None or not research.client.enabled:
        return {
            **base,
            "status": "not_configured",
            "reason": "SEC data is not configured on this server (SEC_USER_AGENT).",
        }
    env = await asyncio.to_thread(research.insider_filings, db, inst, MAX_FILINGS)
    if env.get("data") is None:
        return {**base, "status": env.get("status"), "reason": env.get("reason")}
    cik = env["cik"]
    filings = [f for f in env["data"] if f.get("xml")]

    def spec(f: dict):
        async def compute():
            try:
                xml = await asyncio.to_thread(research.client.filing_xml, cik, f["accession"], f["xml"])
                return _jsonable_form4(await asyncio.to_thread(parse_form4, xml))
            except (ProviderError, ET.ParseError) as err:
                return {"error": getattr(err, "message", "The filing's XML could not be parsed.")}

        return f"sec:form4:{f['accession']}", compute

    parsed = await _cached_many(db, research, [spec(f) for f in filings])
    rows, failed = [], 0
    for f, p in zip(filings, parsed, strict=True):
        if p.get("error"):
            failed += 1
            continue
        who = p["owners"][0] if p.get("owners") else {"name": "Unknown", "roles": []}
        for t in p.get("transactions") or []:
            rows.append({**{k: (Decimal(v) if k in ("shares", "price", "value", "owned_after") and v is not None else v)
                            for k, v in t.items()},
                         "insider": who["name"], "roles": who["roles"], "filed": f["filing_date"],
                         "url": f["index_url"], "form": f["form"]})  # fmt: skip
    rows.sort(key=lambda r: (r.get("date") or "", r["filed"] or ""), reverse=True)
    return {
        **base,
        "status": env.get("status"),
        "filings_read": len(filings) - failed,
        "filings_failed": failed,
        "transactions": rows[:60],
        "summary": [summarize(rows, today, 90), summarize(rows, today, 365)],
        "note": "Non-derivative transactions from the latest Form 4 filings. Codes P and S are open-market trades; "
        "awards, tax withholding and option exercises are not purchases or sales by choice.",
    }


async def ownership(db: Session, market: MarketDataService, research, inst: Instrument, today: date) -> dict:
    h, ins = await asyncio.gather(market.holders(inst.symbol), insiders(db, research, inst, today))
    holders: dict
    if h.value is None:
        holders = {"status": h.meta.status, "reason": h.meta.message or "No holder data."}
    else:
        v = h.value
        holders = {"status": h.meta.status, "source": v.source, "fetched_at": h.meta.fetched_at,
                   "insiders_pct": v.insiders_pct, "institutions_pct": v.institutions_pct,
                   "institutions_float_pct": v.institutions_float_pct, "institutions_count": v.institutions_count,
                   "institutions": [vars(r) for r in v.institutions], "funds": [vars(r) for r in v.funds]}  # fmt: skip
    notes = []
    if er.is_india(inst):
        notes.append(
            "The exchange shareholding pattern (promoter, FII, DII, public, pledged shares) needs a permitted source "
            "(BSE licence or verified NSE terms) and is not shown; Yahoo's insider and institution percentages are "
            "a summary, not that filing."
        )
    return {"symbol": inst.symbol, "holders": holders, "insiders": ins, "notes": notes}

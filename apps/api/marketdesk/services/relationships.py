"""Terminal T10 (stretch): customer and supplier relationships disclosed in the latest annual report.

Sentences from the 10-K (20-F/40-F for foreign filers) that state customer concentration ("Customer A accounted for
12% of net sales") or supplier dependence ("we rely on a single supplier for…"), quoted with a link to the filing.
Found by text rules, not a model: every item is the filing's own words. Low confidence by design — companies need
not name customers, and a quote is not a complete map of the business.
"""

from __future__ import annotations

import asyncio
import re

from sqlalchemy.orm import Session

from marketdesk.models import Instrument
from marketdesk.providers.base import ProviderError
from marketdesk.services import earnings as er

ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "40-F")
_SENT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z(\"“])")
_PCT = re.compile(r"(\d{1,2}(?:\.\d+)?)\s?(%|percent)", re.IGNORECASE)
_REVENUE = re.compile(
    r"\b(revenue|revenues|net sales|sales|total net revenue|trade receivables|accounts receivable)\b", re.IGNORECASE
)
_CUSTOMER = re.compile(r"\b(customers?|clients?|distributors?|resellers?|channel partners?)\b", re.IGNORECASE)
_SUPPLIER = re.compile(
    r"\b(suppliers?|vendors?|manufacturers?|foundr(?:y|ies)|contract manufacturers?|outsourcing partners?|"
    r"manufacturing partners?|(?:single|sole|limited) (?:or limited )?sources?|sources? of supply)\b",
    re.IGNORECASE,
)
_DEPEND = re.compile(
    r"\b(sole[- ]source|single[- ]source|sole supplier|single supplier|limited number of|rely|relies|depend|"
    r"depends|dependent|substantially all|single or limited|limited sources?|concentrated)\b",
    re.IGNORECASE,
)
_NAMED = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&.'-]*)(?:\s(?:[A-Z][A-Za-z0-9&.'-]*|of|and|&)){0,4})\s(?:accounted for|represented|"
    r"comprised|made up)\s(?:approximately\s|about\s)?(\d{1,2}(?:\.\d+)?)\s?(?:%|percent)",
)
_STOP_NAMES = {
    "No",
    "One",
    "Two",
    "The",
    "Our",
    "No One",
    "Sales",
    "Revenue",
    "Revenues",
    "Net Sales",
    "Customer",
    "Customers",
}
MAX_ITEMS = 12
# Sentences about conduct codes or cyber risk mention suppliers without saying the business depends on any.
_NOT_SUPPLY = re.compile(r"code of conduct|cybersecurity|ransomware|malicious|data breach", re.IGNORECASE)
# Without the word "customer", a named share of revenue counts only for something that looks like a company
# ("Revenue from Asia accounted for 12%" names a region, not a customer).
_COMPANY = re.compile(
    r"\b(Inc|Corp|Corporation|Ltd|Limited|LLC|L\.P|Co|Company|plc|PLC|Group|Holdings|AG|SA|N\.V)\b\.?"
)


def _named(sentence: str) -> list[dict]:
    out = []
    for m in _NAMED.finditer(sentence):
        name = m.group(1).strip()
        if name in _STOP_NAMES or name.split()[0] in ("The", "Our", "No", "These", "This"):
            if not re.match(r"^(Customer|Client) [A-Z]$", name):
                continue
        out.append({"name": name, "share_pct": m.group(2)})
    return out


def extract(text: str) -> dict:
    """{customers: [...], suppliers: [...]} — quoted sentences with any named counterparty and percentage."""
    flat = re.sub(r"\s+", " ", text.translate(er._ZERO_WIDTH))
    customers, suppliers, seen = [], [], set()
    for s in _SENT.split(flat):
        s = s.strip()
        if not 40 <= len(s) <= 600 or s in seen or "forward-looking" in s.lower():
            continue
        named = _named(s) if _REVENUE.search(s) else []
        companies = [n for n in named if _COMPANY.search(n["name"])]
        if (_CUSTOMER.search(s) or companies) and _REVENUE.search(s) and _PCT.search(s):
            named = named if _CUSTOMER.search(s) else companies
            seen.add(s)
            customers.append({"quote": s, "named": named})
        elif _SUPPLIER.search(s) and _DEPEND.search(s) and not _NOT_SUPPLY.search(s):
            seen.add(s)
            suppliers.append({"quote": s, "named": []})
    return {"customers": _distinct(customers)[:MAX_ITEMS], "suppliers": _distinct(suppliers)[:MAX_ITEMS]}


def _distinct(items: list[dict]) -> list[dict]:
    """Drop a quote whose words are contained in another kept quote (a heading glued to a repeated sentence)."""
    keys = [" ".join(re.findall(r"[a-z0-9]+", it["quote"].lower())) for it in items]
    out = []
    for i, it in enumerate(items):
        if any(j != i and keys[i] in keys[j] and (len(keys[i]) < len(keys[j]) or j < i) for j in range(len(items))):
            continue
        out.append(it)
    return out


async def relationships(db: Session, research, inst: Instrument) -> dict:
    base = {"symbol": inst.symbol, "confidence": "low",
            "method": "Sentences matched by text rules in the latest annual report (customer + share of revenue + a "
                      "percentage; supplier + a dependence word). Quoted verbatim; not a complete list."}  # fmt: skip
    if inst.country != "US":
        return {**base, "status": "not_applicable", "reason": "Annual-report extraction covers US SEC filers."}
    if research is None or not research.client.enabled:
        return {
            **base,
            "status": "not_configured",
            "reason": "SEC data is not configured on this server.",
        }
    env = await asyncio.to_thread(research.filings, db, inst, 80)
    rows = [r for r in env.get("data") or [] if r["form"] in ANNUAL_FORMS]
    if not rows:
        return {
            **base,
            "status": "missing",
            "reason": env.get("reason") or "No annual report is listed for this company.",
        }
    filing, cik = rows[0], env["cik"]
    key = f"sec:relations:v4:{filing['accession']}"
    payload, _ = await asyncio.to_thread(research._cache_get, db, key)
    if payload is None:
        try:
            text, url = await er._filing_text(research, cik, filing, max_chars=1_500_000)
            payload = {"url": url, **(await asyncio.to_thread(extract, text))}
        except ProviderError as err:
            payload = {"error": err.message}
        await asyncio.to_thread(research._cache_put, db, key, "sec_relations", payload)
    if payload.get("error"):
        return {**base, "status": "unavailable", "reason": f"The annual report could not be read: {payload['error']}"}
    return {
        **base,
        "status": "available",
        "filing": {
            "form": filing["form"],
            "filed": filing["filing_date"],
            "period": filing.get("report_date"),
            "url": payload["url"],
            "index_url": filing.get("index_url"),
        },  # fmt: skip
        "customers": payload["customers"],
        "suppliers": payload["suppliers"],
    }

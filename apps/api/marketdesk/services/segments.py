"""Segment, product and geographic breakdowns from a 10-K's XBRL instance (terminal roadmap T2 stretch goal).

SEC company facts carry only consolidated totals; breakdowns live in the filing's own XBRL instance as facts whose
context has one explicit dimension (business segment, product or service, geography). This module reads that
instance as a stream (elements are discarded as they are read, so a large filing never builds a whole tree), keeps
only revenue and operating-income facts with exactly one of those dimensions over a roughly one-year period, and
returns them by axis and fiscal year. Values are as filed; member names come from the filer's own element names.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET  # documents with a DOCTYPE are refused before parsing (no entity expansion)
from datetime import date
from decimal import Decimal, InvalidOperation

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"
AXES = {
    "StatementBusinessSegmentsAxis": "Business segments",
    "ProductOrServiceAxis": "Products and services",
    "StatementGeographicalAxis": "Geography",
}
CONCEPTS = {  # first available wins for revenue
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "RevenueFromContractWithCustomerIncludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "OperatingIncomeLoss": "operating_income",
}
REVENUE_ORDER = list(k for k, v in CONCEPTS.items() if v == "revenue")
MAX_MEMBERS = 15
# A second dimension that only says "this is an operating segment" (ASU 2023-07 tagging) does not change the breakdown.
NEUTRAL = {("ConsolidationItemsAxis", "OperatingSegmentsMember")}
LINK = "{http://www.xbrl.org/2003/linkbase}"
XLINK = "{http://www.w3.org/1999/xlink}"
TERSE = "http://www.xbrl.org/2003/role/terseLabel"
STANDARD = "http://www.xbrl.org/2003/role/label"


def _neutral(dim) -> bool:
    return (dim.get("dimension", "").split(":", 1)[-1], (dim.text or "").strip().split(":", 1)[-1]) in NEUTRAL


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def member_label(qname: str) -> str:
    """'aapl:GreaterChinaSegmentMember' → 'Greater China'; 'us-gaap:ServiceMember' → 'Service'."""
    name = qname.split(":", 1)[-1]
    name = re.sub(r"(Segment)?Member$", "", name)
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return words.strip() or qname


def parse_instance(raw: bytes) -> dict:
    """{axes: [{axis, label, members: [{member, label, revenue: {fy_end: Decimal}, operating_income: {...}}]}],
    fiscal_year_ends: [date…], currency}. Raises ValueError on a malformed or DOCTYPE-bearing document."""
    if b"<!DOCTYPE" in raw[:4096].upper():
        raise ValueError("The XBRL instance declares a DOCTYPE and was not read.")
    contexts: dict[str, tuple[date, date, str, str] | None] = {}
    facts: list[tuple[str, str, str, Decimal]] = []  # concept, contextRef, unitRef, value
    units: dict[str, str] = {}
    try:
        for _event, el in ET.iterparse(io.BytesIO(raw), events=("end",)):  # noqa: S314 - DOCTYPE refused above
            tag = el.tag
            if tag == f"{XBRLI}context":
                cid = el.get("id") or ""
                start = el.findtext(f"{XBRLI}period/{XBRLI}startDate")
                end = el.findtext(f"{XBRLI}period/{XBRLI}endDate")
                dims = [d for d in el.findall(f".//{XBRLI}segment/{XBRLDI}explicitMember") if not _neutral(d)]
                typed = el.findall(f".//{XBRLI}segment/{XBRLDI}typedMember")
                if start and end and len(dims) == 1 and not typed:
                    axis = dims[0].get("dimension", "").split(":", 1)[-1]
                    member = (dims[0].text or "").strip()
                    if axis in AXES and member:
                        contexts[cid] = (date.fromisoformat(start[:10]), date.fromisoformat(end[:10]), axis, member)
                el.clear()
            elif tag == f"{XBRLI}unit":
                measure = el.findtext(f".//{XBRLI}measure") or ""
                units[el.get("id") or ""] = measure.split(":", 1)[-1]
                el.clear()
            elif _local(tag) in CONCEPTS and el.get("contextRef"):
                try:
                    v = Decimal((el.text or "").strip())
                except InvalidOperation:
                    v = None
                if v is not None and v.is_finite():
                    facts.append((_local(tag), el.get("contextRef"), el.get("unitRef") or "", v))
                el.clear()
    except ET.ParseError as exc:
        raise ValueError(f"The XBRL instance could not be parsed ({exc}).") from exc

    # concept → axis → member → fiscal-year end → value (annual durations only: 350–380 days)
    table: dict[str, dict[str, dict[str, dict[date, Decimal]]]] = {}
    currency = None
    for concept, cref, uref, v in facts:
        ctx = contexts.get(cref)
        if ctx is None:
            continue
        start, end, axis, member = ctx
        if not 350 <= (end - start).days <= 380:
            continue
        currency = currency or units.get(uref)
        table.setdefault(concept, {}).setdefault(axis, {}).setdefault(member, {})[end] = v

    axes_out, ends = [], set()
    for axis, label in AXES.items():
        rev_concept = next((c for c in REVENUE_ORDER if axis in table.get(c, {})), None)
        if rev_concept is None:
            continue
        revenue = table[rev_concept][axis]
        op = table.get("OperatingIncomeLoss", {}).get(axis, {})
        latest = max((max(v) for v in revenue.values()), default=None)
        members = sorted(revenue, key=lambda m: -(revenue[m].get(latest) or Decimal(0)))[:MAX_MEMBERS]
        rows = []
        for m in members:
            rows.append(
                {"member": m, "label": member_label(m), "revenue": revenue[m], "operating_income": op.get(m, {})}
            )
            ends.update(revenue[m])
        axes_out.append({"axis": axis, "label": label, "concept": rev_concept, "members": rows})
    return {"axes": axes_out, "fiscal_year_ends": sorted(ends, reverse=True), "currency": currency}


def parse_labels(raw: bytes, wanted: set[str]) -> dict[str, str]:
    """{'aapl:IPhoneMember': 'iPhone'} from the filing's label linkbase, for the wanted members only (terse label
    first, else the standard label without its ' [Member]' suffix)."""
    if b"<!DOCTYPE" in raw[:4096].upper():
        raise ValueError("The label linkbase declares a DOCTYPE and was not read.")
    keys = {m.replace(":", "_"): m for m in wanted}  # element ids look like aapl_IPhoneMember
    loc: dict[str, str] = {}  # locator label → member
    texts: dict[str, dict[str, str]] = {}  # resource label → role → text
    arcs: list[tuple[str, str]] = []
    for _event, el in ET.iterparse(io.BytesIO(raw), events=("end",)):  # noqa: S314 - DOCTYPE refused above
        tag = el.tag
        if tag == f"{LINK}loc":
            frag = (el.get(f"{XLINK}href") or "").rsplit("#", 1)[-1]
            if frag in keys:
                loc[el.get(f"{XLINK}label") or ""] = keys[frag]
        elif tag == f"{LINK}label":
            texts.setdefault(el.get(f"{XLINK}label") or "", {})[el.get(f"{XLINK}role") or ""] = (el.text or "").strip()
        elif tag == f"{LINK}labelArc":
            arcs.append((el.get(f"{XLINK}from") or "", el.get(f"{XLINK}to") or ""))
        el.clear()
    out: dict[str, str] = {}
    for frm, to in arcs:
        member = loc.get(frm)
        roles = texts.get(to) or {}
        text = roles.get(TERSE) or re.sub(r"\s*\[(Member|Domain)\]$", "", roles.get(STANDARD, ""))
        if member and text and member not in out:
            out[member] = text
    return out


def apply_labels(result: dict, labels: dict[str, str]) -> dict:
    for axis in result["axes"]:
        for m in axis["members"]:
            m["label"] = labels.get(m["member"], m["label"])
    return result


def label_name(files: list[dict]) -> str | None:
    return next((f["name"] for f in files if str(f.get("name", "")).endswith("_lab.xml")), None)


def to_json(result: dict) -> dict:
    """JSON-ready (and cacheable) form: dates as ISO strings, values as decimal strings."""
    return {
        "currency": result["currency"],
        "fiscal_year_ends": [d.isoformat() for d in result["fiscal_year_ends"]],
        "axes": [
            {**a, "members": [
                {**m, "revenue": {k.isoformat(): format(v, "f") for k, v in m["revenue"].items()},
                 "operating_income": {k.isoformat(): format(v, "f") for k, v in m["operating_income"].items()}}
                for m in a["members"]
            ]}
            for a in result["axes"]
        ],
    }  # fmt: skip


def instance_name(files: list[dict]) -> str | None:
    """The filing's extracted XBRL instance (inline-XBRL filings publish it as *_htm.xml)."""
    names = [f["name"] for f in files if isinstance(f.get("name"), str)]
    for n in names:
        if n.endswith("_htm.xml"):
            return n
    skip = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml", "FilingSummary.xml")
    return next((n for n in names if n.endswith(".xml") and not n.endswith(skip)), None)

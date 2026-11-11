"""Terminal T5: a per-security stream of filings and headlines.

Two sources, never mixed up: SEC filings (US registrants, when SEC data is configured) with each 8-K item given its
plain-language label from SEC Form 8-K, and the price provider's headlines (title, publisher, time and link only; no
article body is fetched, summarised or stored). Items are de-duplicated, sorted newest first and carry their source.
Indian exchange announcements need a permitted source (as in T3) and are not fetched.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from marketdesk.models import Instrument
from marketdesk.providers.alpaca import us_symbol
from marketdesk.providers.base import ProviderError
from marketdesk.services import earnings as er
from marketdesk.services.market import MarketDataService

# SEC Form 8-K item captions (General Instructions, Items 1.01–9.01), shortened to plain language.
ITEM_LABELS = {
    "1.01": "Entered a material agreement",
    "1.02": "Ended a material agreement",
    "1.03": "Bankruptcy or receivership",
    "1.04": "Mine safety: shutdown or pattern of violations",
    "1.05": "Material cybersecurity incident",
    "2.01": "Completed an acquisition or disposal of assets",
    "2.02": "Results of operations (earnings release)",
    "2.03": "New material debt or off-balance-sheet obligation",
    "2.04": "Event that accelerates a debt obligation",
    "2.05": "Exit or restructuring costs",
    "2.06": "Material impairment",
    "3.01": "Delisting notice or listing-rule issue",
    "3.02": "Unregistered sale of equity",
    "3.03": "Change to shareholders' rights",
    "4.01": "Change of auditor",
    "4.02": "Earlier financial statements should no longer be relied on",
    "5.01": "Change in control",
    "5.02": "Director or officer change, or executive pay",
    "5.03": "Charter or bylaw amendment; fiscal year change",
    "5.04": "Suspension of trading under employee benefit plans",
    "5.05": "Code of ethics change or waiver",
    "5.06": "Change in shell company status",
    "5.07": "Shareholder vote results",
    "5.08": "Shareholder director nominations",
    "6.01": "ABS informational material",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other events",
    "9.01": "Financial statements and exhibits",
}
# Items that usually signal something worth reading first (shown as "important").
KEY_ITEMS = {"1.01", "1.02", "1.03", "1.05", "2.01", "2.02", "2.05", "2.06", "3.01", "4.01", "4.02", "5.01", "5.02"}
FORM_LABELS = {
    "10-K": "Annual report",
    "10-K/A": "Annual report (amended)",
    "10-Q": "Quarterly report",
    "10-Q/A": "Quarterly report (amended)",
    "20-F": "Annual report (foreign private issuer)",
    "40-F": "Annual report (Canadian issuer)",
    "6-K": "Report of a foreign private issuer",
    "DEF 14A": "Proxy statement",
    "S-1": "Registration statement",
    "S-1/A": "Registration statement (amended)",
    "424B4": "Final prospectus",
    "SC 13D": "Ownership above 5% (active holder)",
    "SC 13G": "Ownership above 5% (passive holder)",
}
CATEGORIES = ("filing", "release", "news")
MAX_ITEMS = 120


def filing_item(row: dict) -> dict:
    """One SEC filing as a stream item with a plain-language headline."""
    form = row["form"]
    items = [i for i in row.get("items") or [] if i != "9.01"] or list(row.get("items") or [])
    if form.startswith("8-K"):
        labels = [ITEM_LABELS.get(i, f"Item {i}") for i in items] or ["Current report"]
        headline = "; ".join(labels)
        if form.endswith("/A"):
            headline += " (amended)"
    else:
        headline = FORM_LABELS.get(form, row.get("description") or form)
        if row.get("report_date"):
            headline += f" for the period ended {row['report_date']}"
    category = "release" if form.startswith("8-K") and {"2.02", "7.01", "8.01"} & set(items) else "filing"
    return {
        "at": row["filing_date"],
        "precision": "date",
        "category": category,
        "headline": headline,
        "form": form,
        "items": [{"code": i, "label": ITEM_LABELS.get(i, f"Item {i}")} for i in row.get("items") or []],
        "important": bool(KEY_ITEMS & set(items)) or form in ("10-K", "20-F", "SC 13D"),
        "source": "SEC EDGAR",
        "publisher": "SEC EDGAR",
        "url": row.get("document_url") or row.get("index_url"),
        "index_url": row.get("index_url"),
    }


def news_item(n) -> dict:
    return {
        "at": n.published_at.isoformat() if n.published_at else None,
        "precision": "instant" if n.published_at else "unknown",
        "category": "release" if n.kind == "press_release" else "news",
        "headline": n.title,
        "kind": n.kind,
        "important": False,
        "source": "provider",
        "publisher": n.publisher,
        "url": n.url,
    }


_WORDS = re.compile(r"[a-z0-9]+")


def _key(headline: str) -> str:
    return " ".join(_WORDS.findall(headline.lower()))[:120]


def merge(items: list[dict]) -> list[dict]:
    """De-duplicate by link and by normalised headline (syndicated copies), newest first; undated items last."""
    seen_url: set[str] = set()
    seen_title: set[str] = set()
    out = []
    for it in items:
        url = (it.get("url") or "").split("?")[0].rstrip("/").lower()
        title = _key(it["headline"])
        if (url and url in seen_url) or (it["source"] != "SEC EDGAR" and title in seen_title):
            continue
        if url:
            seen_url.add(url)
        seen_title.add(title)
        out.append(it)

    def sort_key(it):
        at = it.get("at")
        if not at:
            return ""
        return at if "T" in at else f"{at}T23:59:59"  # a filing date sorts at the end of its day

    return sorted(out, key=sort_key, reverse=True)[:MAX_ITEMS]


def alpaca_item(n: dict, symbol: str) -> dict:
    others = [s for s in n.get("symbols") or [] if s != symbol]
    return {
        "at": n["published_at"].isoformat() if n.get("published_at") else None,
        "precision": "instant" if n.get("published_at") else "unknown",
        "category": "news",
        "headline": n["title"],
        "kind": "news",
        "important": False,
        "source": "provider",
        "publisher": n.get("publisher"),
        "url": n.get("url"),
        "related": others[:6],
        "broad": len(others) >= 6,  # a market-wide piece that merely tags this symbol among many
    }


async def _alpaca_news(alpaca, inst: Instrument) -> list[dict] | None:
    if alpaca is None or not alpaca.enabled or inst.country != "US" or us_symbol(inst.symbol) is None:
        return None
    try:
        rows = await asyncio.to_thread(alpaca.news, inst.symbol, 40)
    except ProviderError:
        return None
    return [alpaca_item(n, inst.symbol.replace("-", ".")) for n in rows]


async def stream(db: Session, market: MarketDataService, research, inst: Instrument, alpaca=None) -> dict:
    sources, notes, items = [], [], []
    tagged = await _alpaca_news(alpaca, inst)
    news = await market.news(inst.symbol)
    if tagged:
        items += tagged
        sources.append(
            "Headlines: Benzinga via Alpaca, tagged with this symbol; title, publisher and link only. Stories that "
            "tag many symbols are marked as broad."
        )
    elif news.value is not None:
        items += [news_item(n) for n in news.value]
        sources.append(
            f"Headlines: {market.source} ({news.meta.status}); title, publisher and link only. "
            + (
                "Yahoo's results for a symbol can include stories about related companies."
                if market.source == "yahoo"
                else ""
            )
        )
    elif news.meta.message:
        notes.append(f"Headlines unavailable: {news.meta.message}")
    sec_on = research is not None and research.client.enabled
    if inst.country == "US" and sec_on:
        env = await asyncio.to_thread(research.filings, db, inst, 80)
        rows = env.get("data") or []
        items += [filing_item(r) for r in rows]
        sources.append("Filings: SEC EDGAR (8-K items labelled from SEC Form 8-K)")
        if env.get("reason") and not rows:
            notes.append(env["reason"])
    elif inst.country == "US":
        notes.append("SEC data is not configured on this server (SEC_USER_AGENT): filings are not shown.")
    elif er.is_india(inst):
        notes.append(
            "Exchange announcements for Indian listings need a permitted source (BSE licence or verified NSE terms) "
            "and are not shown."
        )
    merged = merge(items)
    counts = {c: sum(1 for i in merged if i["category"] == c) for c in CATEGORIES}
    return {
        "symbol": inst.symbol,
        "as_of": datetime.now(UTC).isoformat(),
        "items": merged,
        "counts": counts,
        "fetched_at": news.meta.fetched_at.isoformat() if news.meta.fetched_at else None,
        "sources": sources,
        "notes": notes,
        "policy": "Headlines link to the publisher; MarketDesk does not fetch, store or summarise article text. "
        "Filing headlines are SEC's own item captions, not a reading of the filing.",
    }

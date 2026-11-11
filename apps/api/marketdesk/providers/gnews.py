"""Headlines from the Google News RSS search feed, limited to established publishers (DECISIONS #71).

Only the fixed news.google.com RSS host is requested, with a query built from the company's name (never a URL
from a user). Title, publisher, time and link only — no article text is fetched. Results are cached in memory for
15 minutes per query. XML documents that declare a DOCTYPE are refused, so no entity declaration is processed.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET  # noqa: S405 - DOCTYPEs are refused before parsing
from datetime import UTC
from email.utils import parsedate_to_datetime

from marketdesk.providers.base import NewsItem, ProviderError

FEED = "https://news.google.com/rss/search"
TTL = 15 * 60

# Established news organisations, business papers and company press-release wires. A headline from any other
# outlet (blogs, social posts, brokerage marketing) is not shown.
CREDIBLE = {
    # global and US
    "reuters", "bloomberg", "bloomberg.com", "associated press", "ap news", "cnbc", "financial times", "ft",
    "the wall street journal", "wsj", "barron's", "barrons.com", "marketwatch", "the new york times",
    "the washington post", "the economist", "bbc", "bbc news", "cnn", "cnn business", "fortune", "forbes",
    "business insider", "axios", "the guardian", "nikkei asia", "yahoo finance", "investor's business daily",
    "the information", "techcrunch", "the verge", "politico", "fox business", "abc news", "cbs news", "nbc news",
    "npr", "time", "los angeles times", "investing.com", "morningstar", "kiplinger", "the motley fool",
    "motley fool", "thestreet", "zacks", "seeking alpha",
    # India
    "the economic times", "economic times", "et now", "livemint", "mint", "business standard", "moneycontrol",
    "ndtv profit", "ndtv", "the hindu businessline", "businessline", "the hindu", "financial express",
    "the financial express", "hindustan times", "the times of india", "times of india", "cnbctv18",
    "cnbc tv18", "cnbc-tv18", "zee business", "bq prime", "the print", "theprint", "india today", "business today",
    "the indian express", "indian express", "deccan herald", "press trust of india", "pti",
    "breakingviews", "reuters breakingviews", "firstpost", "the week", "news18", "outlook business",
    # financial newswires
    "benzinga", "mt newswires", "dow jones newswires", "dow jones",
    # press-release wires
    "pr newswire", "business wire", "globenewswire", "accesswire", "access newswire",
}  # fmt: skip


def credible(publisher: str | None) -> bool:
    return bool(publisher) and publisher.strip().lower() in CREDIBLE


def parse_feed(xml_text: str, limit: int = 60) -> list[NewsItem]:
    """Pure: RSS XML → NewsItem list (title without its " - Publisher" suffix, publisher, link, UTC time)."""
    if "<!DOCTYPE" in xml_text[:4000].upper():
        raise ProviderError("malformed", "The news feed declared a DOCTYPE and was not read.")
    try:
        root = ET.fromstring(xml_text)  # noqa: S314 - see the import note
    except ET.ParseError:
        raise ProviderError("malformed", "The news feed was not valid XML.") from None
    out: list[NewsItem] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        src = item.find("source")
        publisher = (src.text or "").strip() if src is not None and src.text else None
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].rstrip()
        if not title or not link.startswith("https://"):
            continue
        when = None
        try:
            raw = item.findtext("pubDate")
            when = parsedate_to_datetime(raw).astimezone(UTC) if raw else None
        except (TypeError, ValueError):
            when = None
        out.append(NewsItem(title[:300], publisher[:80] if publisher else None, link[:1000], when, "news"))
        if len(out) >= limit:
            break
    return out


class GoogleNews:
    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout
        self._cache: dict[tuple, tuple[float, list[NewsItem]]] = {}
        self._lock = threading.Lock()

    def search(self, company: str, india: bool) -> list[NewsItem]:
        """Recent headlines that mention the company by name (last 14 days)."""
        name = " ".join(company.replace('"', " ").split())[:80]
        if len(name) < 2:
            return []
        key = (name.lower(), india)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < TTL:
                return hit[1]
        q = f'"{name}" when:14d'
        params = {"q": q, "hl": "en-IN" if india else "en-US", "gl": "IN" if india else "US",
                  "ceid": "IN:en" if india else "US:en"}  # fmt: skip
        req = urllib.request.Request(  # noqa: S310 (fixed host)
            f"{FEED}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "MarketDesk/1.0 (headline reader)"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                items = parse_feed(resp.read(3_000_000).decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            raise ProviderError("upstream_unavailable", f"The news feed failed (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError):
            raise ProviderError("timeout", "The news feed did not respond.", retryable=True) from None
        with self._lock:
            if len(self._cache) > 200:
                self._cache.clear()
            self._cache[key] = (time.monotonic(), items)
        return items

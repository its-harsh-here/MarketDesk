"""SEC EDGAR client (server-side only; https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

- data.sec.gov submissions and XBRL company facts plus www.sec.gov/files/company_tickers.json; no API key exists.
- Fair access (SEC webmaster FAQ, checked 3 Nov 2026): at most 10 requests per second, and every request must declare
  a User-Agent with the application name and an administrative contact email. MarketDesk stays well below the limit
  (SEC_MAX_REQUESTS_PER_SECOND, default 5) with a process-wide token bucket, and sends nothing at all unless
  SEC_USER_AGENT is configured with a contact address.
- 429/5xx responses are retried a bounded number of times with backoff; no limit is ever bypassed.
"""

from __future__ import annotations

import gzip
import html
import json
import random
import re
import threading
import time
import urllib.error
import urllib.request

from marketdesk.providers.base import ProviderError

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_UA_RE = re.compile(r"^\S.{2,}\s\S+@\S+\.\S+$")
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_DOC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(htm|html|txt)$", re.IGNORECASE)
_XML_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.xml$", re.IGNORECASE)
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)


def _accession(value: str) -> str:
    if not _ACCESSION_RE.match(value or ""):
        raise ProviderError("unsupported", "Not an SEC accession number.")
    return value


_HTML_RE = re.compile(r"<(html|body|div|p|span|table|br)\b", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_RE = re.compile(
    r"<(?:br|hr|/?(?:p|div|li|tr|h[1-6]|table|section|article|blockquote|ul|ol|center|dt|dd))\b[^>]*>", re.IGNORECASE
)


def html_to_text(markup: str) -> str:
    """Readable text from a filing: tags removed, entities decoded, one line per block (paragraph, division, list
    item, table row, heading). In HTML, line breaks in the source are ordinary spaces, so paragraphs wrapped in the
    source stay whole and inline-XBRL reports (few source line breaks) still split into paragraphs. Plain-text
    documents keep their own lines."""
    if _HTML_RE.search(markup):
        markup = _BLOCK_RE.sub("\n", re.sub(r"\s+", " ", _SCRIPT_RE.sub(" ", markup)))
    text = html.unescape(_TAG_RE.sub(" ", markup))
    return re.sub(r"[ \t\r\f\v\xa0]+", " ", re.sub(r"\s*\n\s*", "\n", text)).strip()


def user_agent_problem(ua: str | None) -> str | None:
    if not ua:
        return "SEC filings are not configured on this server."
    if not _UA_RE.match(ua.strip()):
        return "SEC filings are not configured correctly on this server."
    return None


def filing_index_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"


def filing_document_url(cik: int, accession: str, document: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"


class _RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / max(0.1, min(per_second, 9.0))  # never above SEC's 10/s
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


class SecClient:
    def __init__(self, user_agent: str | None, per_second: float = 5.0, timeout: float = 20.0, retries: int = 2):
        self.user_agent = (user_agent or "").strip()
        self.problem = user_agent_problem(self.user_agent)
        self.timeout = timeout
        self.retries = retries
        self._limiter = _RateLimiter(per_second)

    @property
    def enabled(self) -> bool:
        return self.problem is None

    def _fetch(self, url: str, accept: str, max_bytes: int = 30_000_000) -> bytes:
        if not self.enabled:
            raise ProviderError("unsupported", self.problem or "SEC access is not configured.")
        for attempt in range(self.retries + 1):
            self._limiter.wait()
            req = urllib.request.Request(  # noqa: S310 (only fixed https SEC URLs are ever requested)
                url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip", "Accept": accept}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (fixed SEC hosts)
                    raw = resp.read(max_bytes + 1)
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                if len(raw) > max_bytes:
                    raw = raw[:max_bytes]
                return raw
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise ProviderError("missing", "SEC has no data for this company or filing.") from exc
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt == self.retries:
                    kind = "rate_limited" if exc.code == 429 else "upstream_unavailable"
                    raise ProviderError(kind, f"SEC request failed (HTTP {exc.code}).", retryable=retryable) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == self.retries:
                    raise ProviderError("timeout", "SEC did not respond in time.", retryable=True) from exc
            time.sleep(min(8.0, 0.5 * 2**attempt) * (0.5 + random.random()))  # noqa: S311 (jitter only)
        raise AssertionError("unreachable")  # pragma: no cover

    def _get_json(self, url: str):
        raw = self._fetch(url, "application/json")
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise ProviderError("malformed", "SEC returned data that is not valid JSON.") from exc

    def filing_files(self, cik: int, accession: str) -> list[dict]:
        """The documents in one filing (name, type, size) from the archive's index.json."""
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{_accession(accession).replace('-', '')}/index.json"
        data = self._get_json(url)
        items = ((data or {}).get("directory") or {}).get("item") or []
        return [i for i in items if isinstance(i, dict) and i.get("name")]

    def document_text(
        self, cik: int, accession: str, name: str, max_chars: int = 12_000, max_bytes: int = 3_000_000
    ) -> str:
        """Plain text of one filing document (HTML stripped), cut to max_chars. Only SEC archive URLs are built.
        Inline-XBRL annual reports carry megabytes of hidden data before the visible text: comparisons of whole
        sections pass a larger `max_bytes`."""
        if not _DOC_RE.match(name or ""):
            raise ProviderError("unsupported", "Only plain filing documents (.htm, .html, .txt) can be read.")
        raw = self._fetch(filing_document_url(int(cik), _accession(accession), name), "text/html", max_bytes)
        return html_to_text(raw.decode("utf-8", errors="replace"))[:max_chars]

    def filing_bytes(self, cik: int, accession: str, name: str, max_bytes: int = 40_000_000) -> bytes:
        """Raw bytes of one .xml filing document (an XBRL instance or label linkbase), for stream parsing."""
        if not _XML_RE.match(name or ""):
            raise ProviderError("unsupported", "Only plain .xml filing documents can be read.")
        raw = self._fetch(filing_document_url(int(cik), _accession(accession), name), "application/xml", max_bytes)
        if len(raw) >= max_bytes:
            raise ProviderError("too_large", "The filing's XBRL data is larger than MarketDesk reads.")
        return raw

    def filing_xml(self, cik: int, accession: str, name: str, max_bytes: int = 1_000_000) -> str:
        """Raw XML of one filing document (e.g. a Form 4 ownership document). Documents with a DOCTYPE are refused,
        so no entity declaration from a filing is ever processed."""
        if not _XML_RE.match(name or ""):
            raise ProviderError("unsupported", "Only plain .xml filing documents can be read.")
        raw = self._fetch(filing_document_url(int(cik), _accession(accession), name), "application/xml", max_bytes)
        text = raw.decode("utf-8", errors="replace")
        if "<!DOCTYPE" in text[:4000].upper():
            raise ProviderError("malformed", "The filing's XML declares a DOCTYPE and was not read.")
        return text

    def ticker_map(self) -> dict[str, tuple[int, str]]:
        """Ticker -> (CIK, registrant name) from SEC's published association file."""
        data = self._get_json(TICKERS_URL)
        if not isinstance(data, dict):
            raise ProviderError("malformed", "SEC ticker file had an unexpected shape.")
        out = {}
        for row in data.values():
            try:
                out[str(row["ticker"]).upper()] = (int(row["cik_str"]), str(row["title"]))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def submissions(self, cik: int) -> dict:
        data = self._get_json(SUBMISSIONS_URL.format(cik=cik))
        if not isinstance(data, dict) or "filings" not in data:
            raise ProviderError("malformed", "SEC submissions had an unexpected shape.")
        return data

    def companyfacts(self, cik: int) -> dict:
        data = self._get_json(COMPANYFACTS_URL.format(cik=cik))
        if not isinstance(data, dict) or not isinstance(data.get("facts"), dict):
            raise ProviderError("malformed", "SEC company facts had an unexpected shape.")
        return data

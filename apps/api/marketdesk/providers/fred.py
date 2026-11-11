"""FRED (Federal Reserve Bank of St. Louis) API client for US official statistics (terminal T8).

Only fixed api.stlouisfed.org endpoints are requested. The key travels as a query parameter (FRED's design), so it
is never logged and every error message is built without the URL.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from marketdesk.providers.base import ProviderError

BASE = "https://api.stlouisfed.org/fred"
_ID = re.compile(r"^[A-Z0-9_]{1,30}$")
_KEY = re.compile(r"^[a-z0-9]{32}$")


class FredClient:
    def __init__(self, api_key: str | None, timeout: float = 15.0):
        key = (api_key or "").strip()
        self.problem = None if _KEY.match(key) else (
            "FRED is not configured (FRED_API_KEY)." if not key else "FRED_API_KEY is not a 32-character FRED key."
        )  # fmt: skip
        self._key = key if self.problem is None else None
        self.timeout = timeout
        self._last = 0.0

    @property
    def enabled(self) -> bool:
        return self._key is not None

    def _get(self, path: str, params: dict) -> dict:
        if not self.enabled:
            raise ProviderError("unsupported", self.problem or "FRED is not configured.")
        wait = 0.6 - (time.monotonic() - self._last)  # FRED allows 120 requests a minute
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        query = urllib.parse.urlencode({**params, "api_key": self._key, "file_type": "json"})
        req = urllib.request.Request(f"{BASE}/{path}?{query}", headers={"User-Agent": "MarketDesk"})  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (fixed FRED host)
                data = json.loads(resp.read(5_000_000))
        except urllib.error.HTTPError as exc:
            kind = (
                "rate_limited" if exc.code == 429 else ("missing" if exc.code in (400, 404) else "upstream_unavailable")
            )
            raise ProviderError(kind, f"FRED request failed (HTTP {exc.code}).", retryable=exc.code >= 429) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise ProviderError("timeout", "FRED did not respond with valid data.", retryable=True) from None
        if isinstance(data, dict) and data.get("error_message"):
            raise ProviderError("missing", "FRED rejected the request.")
        return data

    def series(self, series_id: str) -> dict:
        if not _ID.match(series_id):
            raise ProviderError("unsupported", "Not a FRED series id.")
        rows = self._get("series", {"series_id": series_id}).get("seriess") or []
        if not rows:
            raise ProviderError("missing", f"FRED has no series {series_id}.")
        return rows[0]

    def observations(self, series_id: str, start: str) -> list[dict]:
        if not _ID.match(series_id):
            raise ProviderError("unsupported", "Not a FRED series id.")
        return (
            self._get("series/observations", {"series_id": series_id, "observation_start": start}).get("observations")
            or []
        )

    def release_dates(self, start: str, end: str, limit: int = 200) -> list[dict]:
        params = {"realtime_start": start, "realtime_end": end, "limit": limit, "sort_order": "asc",
                  "include_release_dates_with_no_data": "true"}  # fmt: skip
        return self._get("releases/dates", params).get("release_dates") or []

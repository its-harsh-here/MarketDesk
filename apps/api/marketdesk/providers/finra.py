"""FINRA consolidated short interest (terminal T6). Optional; off unless the owner configures FINRA API credentials.

FINRA's Query API terms require access through credentials issued by FINRA (a free Individual account can create a
"Public" credential in the FINRA API Console). The data is for non-commercial personal use and FINRA must be named as
its owner and source. OAuth 2.0 client credentials: the client ID and secret are exchanged for a bearer token
(cached below its stated lifetime), which is sent with each data request. Documentation read on 5 Nov 2026:
developer.finra.org/docs (Authorization; POST Data; Sorting Restrictions; Consolidated Short Interest).
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request

from marketdesk.providers.base import ProviderError

TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"  # noqa: S105 (a URL, not a secret)
DATA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
FIELDS = [
    "settlementDate",
    "symbolCode",
    "issueName",
    "marketClassCode",
    "currentShortPositionQuantity",
    "previousShortPositionQuantity",
    "changePercent",
    "averageDailyVolumeQuantity",
    "daysToCoverQuantity",
    "stockSplitFlag",
    "revisionFlag",
]
ATTRIBUTION = "FINRA (owner and source of the short interest data)"


def _json(raw: bytes, what: str):
    """Parse a FINRA response; anything that is not JSON becomes a ProviderError (never an unhandled error)."""
    try:
        return json.loads(raw)
    except ValueError:
        head = raw[:20].decode("utf-8", errors="replace").strip().split("\n")[0][:20]
        raise ProviderError("malformed", f"FINRA's {what} response was not JSON (starts {head!r}).") from None


class FinraClient:
    def __init__(self, client_id: str | None, client_secret: str | None, timeout: float = 20.0):
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.timeout = timeout
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    @property
    def problem(self) -> str | None:
        if not self.client_id or not self.client_secret:
            return (
                "Not configured: FINRA's terms require API credentials. Create a free Individual account in the FINRA "
                "API Console, make a Public credential, and set FINRA_CLIENT_ID and FINRA_CLIENT_SECRET on the server."
            )
        return None

    @property
    def enabled(self) -> bool:
        return self.problem is None

    def _request(self, req: urllib.request.Request) -> bytes:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (fixed FINRA hosts)
                return resp.read(5_000_000)
        except urllib.error.HTTPError as exc:
            kind = {401: "unauthorized", 403: "unauthorized", 429: "rate_limited"}.get(exc.code, "upstream_unavailable")
            if 400 <= exc.code < 500 and exc.code not in (401, 403, 429):
                kind = "bad_request"
            raise ProviderError(kind, f"FINRA returned HTTP {exc.code}.", retryable=exc.code >= 500) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("upstream_unavailable", "FINRA could not be reached.", retryable=True) from exc

    def token(self) -> str:
        with self._lock:
            if self._token and self._token[1] > time.monotonic():
                return self._token[0]
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            req = urllib.request.Request(TOKEN_URL, method="POST", headers={"Authorization": f"Basic {basic}"})
            body = _json(self._request(req) or b"{}", "token")
            if not isinstance(body, dict):
                raise ProviderError("malformed", "FINRA's token response was not a JSON object.")
            tok = body.get("access_token")
            if not tok:
                raise ProviderError("unauthorized", "FINRA did not issue an access token; check the credentials.")
            try:
                life = float(body.get("expires_in") or 0)
            except (TypeError, ValueError):
                life = 0.0
            # The docs suggest caching for 30 minutes; never beyond the stated lifetime.
            self._token = (tok, time.monotonic() + max(60.0, min(life - 60, 1800.0) if life else 1800.0))
            return tok

    def short_interest(self, symbol: str, limit: int = 30) -> list[dict]:
        """The symbol's short-interest records (about one rolling year, two per month), newest first.
        Sorting on the server needs an equality filter on the settlement date, so records are sorted here."""
        last_err: ProviderError | None = None
        for compare in ("EQUAL", "equal"):  # the docs show both spellings
            body = {
                "limit": limit,
                "fields": FIELDS,
                "compareFilters": [{"compareType": compare, "fieldName": "symbolCode", "fieldValue": symbol.upper()}],
            }
            req = urllib.request.Request(
                DATA_URL,
                data=json.dumps(body).encode(),
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.token()}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            try:
                raw = self._request(req)
            except ProviderError as err:
                if err.kind == "bad_request":
                    last_err = err
                    continue
                raise
            rows = _json(raw or b"[]", "data")
            if not isinstance(rows, list):
                raise ProviderError("malformed", "FINRA returned an unexpected response shape.")
            rows = [r for r in rows if isinstance(r, dict) and r.get("settlementDate")]
            return sorted(rows, key=lambda r: r["settlementDate"], reverse=True)
        raise last_err or ProviderError("bad_request", "FINRA rejected the query.")

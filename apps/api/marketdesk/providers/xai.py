"""xAI (Grok) Responses API client, standard library only.

Verified against docs.x.ai on 4 Nov 2026: base URL https://api.x.ai/v1, POST /responses (the primary interface for
text, reasoning and tool use), function tools returned as output items of type "function_call" with a call_id and
continued with "function_call_output" items plus previous_response_id; structured output through
text.format = {type: "json_schema", name, schema, strict}; usage reports input/output tokens and
cost_in_usd_ticks (10,000,000,000 ticks = 1 USD).

The key is sent only in the Authorization header and is never logged, echoed in errors, or exposed to the browser.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request

TICKS_PER_USD = 10_000_000_000


class XaiError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind  # auth | rate_limited | unavailable | timeout | bad_request | malformed
        self.message = message
        self.status = status


class XaiClient:
    provider = "xai"

    def __init__(self, api_key: str | None, base_url: str, model: str, timeout: float = 90.0, retries: int = 1):
        # Hosting dashboards make it easy to paste surrounding whitespace or quotes; a key never contains them.
        self._key = (api_key or "").strip().strip("'\"").strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def key_format(self) -> str | None:
        """A non-secret description of the configured key's shape, to diagnose a wrong key without revealing it."""
        if not self._key:
            return None
        shape = "starts with 'xai-'" if self._key.startswith("xai-") else "does not have the expected prefix"
        return f"{shape}, {len(self._key)} characters"

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self._key:
            raise XaiError("auth", "No AI service key is configured.")
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(  # noqa: S310 (fixed https xAI base URL from settings)
                f"{self.base_url}{path}",
                data=data,
                method=method,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "MarketDesk",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                    raw = resp.read()
                try:
                    return json.loads(raw)
                except ValueError as exc:
                    raise XaiError("malformed", "The AI service returned a response that is not JSON.") from exc
            except urllib.error.HTTPError as exc:
                detail = _error_detail(exc)
                if exc.code in (401, 403) or (exc.code == 400 and "api key" in detail.lower()):
                    raise XaiError(
                        "auth",
                        f"The AI service rejected the API key (HTTP {exc.code}){detail}",
                        exc.code,
                    ) from exc
                if exc.code == 429:
                    if attempt < self.retries:
                        time.sleep(min(8.0, 2.0 * (attempt + 1)))
                        continue
                    raise XaiError("rate_limited", "AI service rate or credit limit reached (HTTP 429).", 429) from exc
                if exc.code >= 500:
                    if attempt < self.retries:
                        time.sleep(1.0 + random.random())  # noqa: S311 (jitter only)
                        continue
                    raise XaiError("unavailable", f"AI service unavailable (HTTP {exc.code}).", exc.code) from exc
                raise XaiError(
                    "bad_request", f"AI service refused the request (HTTP {exc.code}){detail}", exc.code
                ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.retries:
                    continue
                raise XaiError("timeout", "The AI service did not respond in time.") from exc
        raise AssertionError("unreachable")  # pragma: no cover

    def create_response(self, body: dict) -> dict:
        return self._request("POST", "/responses", {"model": self.model, **body})

    def list_models(self) -> list[str]:
        data = self._request("GET", "/models")
        return [str(m.get("id")) for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """A short, sanitized reason from an xAI error body (never headers, never the request)."""
    try:
        body = json.loads(exc.read() or b"{}")
    except (ValueError, OSError):
        return "."
    msg = body.get("error") if isinstance(body, dict) else None
    if isinstance(msg, dict):
        msg = msg.get("message")
    if not isinstance(msg, str) or not msg.strip():
        msg = body.get("message") if isinstance(body, dict) else None
    return f": {str(msg).strip()[:160]}" if msg else "."


def usage_cost_usd(usage: dict | None) -> float | None:
    """The cost xAI reports for one response, in USD (None when not reported)."""
    if not isinstance(usage, dict):
        return None
    ticks = usage.get("cost_in_usd_ticks")
    if isinstance(ticks, int | float):
        return float(ticks) / TICKS_PER_USD
    nano = usage.get("cost_in_nano_usd")
    if isinstance(nano, int | float):
        return float(nano) / 1e9
    return None

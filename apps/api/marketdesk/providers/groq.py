"""Groq chat-completions client (OpenAI-compatible), standard library only.

Verified against console.groq.com/docs on 4 Nov 2026: POST https://api.groq.com/openai/v1/chat/completions with a
Bearer key; structured output through response_format = {type: "json_schema", json_schema: {name, strict, schema}}
(strict on openai/gpt-oss-120b, gpt-oss-20b, qwen/qwen3.8-27b); structured output cannot be combined with tool use or
streaming; reasoning_effort (low/medium/high on gpt-oss) and include_reasoning=false; 429 with retry-after when a rate
limit is hit; x-ratelimit-* headers report remaining requests (per day) and tokens (per minute).

The key is sent only in the Authorization header and is never logged, echoed in errors, or exposed to the browser.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request

from marketdesk.providers.xai import XaiError as AiError


class GroqClient:
    provider = "groq"

    def __init__(self, api_key: str | None, base_url: str, model: str, timeout: float = 90.0, retries: int = 1):
        self._key = (api_key or "").strip().strip("'\"").strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.last_limits: dict = {}

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def key_format(self) -> str | None:
        if not self._key:
            return None
        shape = "starts with 'gsk_'" if self._key.startswith("gsk_") else "does not start with 'gsk_' (Groq keys do)"
        return f"{shape}, {len(self._key)} characters"

    def chat(self, body: dict) -> dict:
        if not self._key:
            raise AiError("auth", "No Groq API key is configured.")
        data = json.dumps({"model": self.model, **body}).encode()
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(  # noqa: S310 (fixed https Groq base URL from settings)
                f"{self.base_url}/chat/completions",
                data=data,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "MarketDesk",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                    self._record_limits(resp.headers)
                    raw = resp.read()
                try:
                    return json.loads(raw)
                except ValueError as exc:
                    raise AiError("malformed", "Groq returned a response that is not JSON.") from exc
            except urllib.error.HTTPError as exc:
                self._record_limits(exc.headers)
                detail = _error_detail(exc)
                if exc.code in (401, 403) or (exc.code == 400 and "api key" in detail.lower()):
                    raise AiError(
                        "auth", f"Groq rejected the API key (HTTP {exc.code}){detail} Use a key from console.groq.com."
                    ) from exc
                if exc.code == 413:
                    raise AiError(
                        "too_large", f"The request is larger than Groq allows for this model{detail}"
                    ) from exc
                if exc.code == 429:
                    wait = _retry_after(exc.headers)
                    if attempt < self.retries and wait is not None and wait <= 20:
                        time.sleep(wait + 0.5)
                        continue
                    when = f" Try again in about {int(wait)} seconds." if wait else ""
                    raise AiError("rate_limited", f"Groq free-tier rate limit reached (HTTP 429).{when}", 429) from exc
                if exc.code >= 500:
                    if attempt < self.retries:
                        time.sleep(1.0 + random.random())  # noqa: S311 (jitter only)
                        continue
                    raise AiError("unavailable", f"Groq is unavailable (HTTP {exc.code}).", exc.code) from exc
                raise AiError("bad_request", f"Groq refused the request (HTTP {exc.code}){detail}", exc.code) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.retries:
                    continue
                raise AiError("timeout", "Groq did not respond in time.") from exc
        raise AssertionError("unreachable")  # pragma: no cover

    def _record_limits(self, headers) -> None:
        if not headers:
            return
        keys = {
            "x-ratelimit-remaining-requests": "remaining_requests_today",
            "x-ratelimit-limit-requests": "requests_per_day",
            "x-ratelimit-remaining-tokens": "remaining_tokens_this_minute",
            "x-ratelimit-limit-tokens": "tokens_per_minute",
        }
        found = {name: headers.get(h) for h, name in keys.items() if headers.get(h) is not None}
        if found:
            self.last_limits = {**found, "observed_at": time.time()}


def _retry_after(headers) -> float | None:
    try:
        return float(headers.get("retry-after")) if headers and headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read() or b"{}")
    except (ValueError, OSError):
        return "."
    msg = body.get("error") if isinstance(body, dict) else None
    if isinstance(msg, dict):
        msg = msg.get("message")
    return f": {str(msg).strip()[:200]}" if msg else "."

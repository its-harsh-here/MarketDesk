"""Optional alert delivery to a Telegram chat through the Telegram Bot API (DECISIONS #73).

Configured with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID; without both, no channel exists and the product says so.
Only the fixed api.telegram.org host is requested. The token is part of the request path (Telegram's design), so
error messages are built without the URL and the token is never logged.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

API = "https://api.telegram.org"
_TOKEN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
_CHAT = re.compile(r"^-?\d{3,20}$|^@[A-Za-z0-9_]{5,64}$")


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, timeout: float = 10.0):
        self._token, self.chat_id, self.timeout = token, chat_id, timeout

    @staticmethod
    def problem(token: str | None, chat_id: str | None) -> str | None:
        if not token or not chat_id:
            return "Telegram delivery is not configured on this server."
        if not _TOKEN.match(token.strip()) or not _CHAT.match(chat_id.strip()):
            return "Telegram delivery is configured with an invalid bot token or chat id."
        return None

    def text(self, event) -> str:
        symbol = getattr(getattr(getattr(event, "alert", None), "instrument", None), "symbol", None)
        head = f"MarketDesk alert{f' · {symbol}' if symbol else ''}"
        body = (event.explanation or "").strip()[:900]
        link = f"\n{event.link}" if getattr(event, "link", None) else ""
        return f"{head}\n{body}{link}"

    def deliver(self, event) -> None:
        payload = json.dumps({"chat_id": self.chat_id, "text": self.text(event), "disable_web_page_preview": True})
        req = urllib.request.Request(  # noqa: S310 (fixed host)
            f"{API}/bot{self._token}/sendMessage", data=payload.encode(), headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                data = json.loads(resp.read(100_000) or b"{}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Telegram refused the message (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise RuntimeError("Telegram did not respond.") from None
        if not data.get("ok"):
            raise RuntimeError("Telegram did not accept the message.")

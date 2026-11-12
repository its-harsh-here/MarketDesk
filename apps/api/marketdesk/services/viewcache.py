"""Short-lived cache of assembled research views (docs/PERFORMANCE_ROADMAP.md 3.4).

Risk, earnings, financial analysis and the news stream are rebuilt from already-cached data on every visit, which on a
small shared CPU (Render Free) costs 1–5 s each time. The finished payload is kept here for a few minutes, so switching
tabs or coming back is instant. Bounded by entry count; payloads are small JSON-ready dicts (a few KB each).

Anything the user changes (any successful POST/PATCH/PUT/DELETE) clears the whole cache, so a view never shows a
watchlist, holding or setting from before the change. Market data inside a view is as old as the view says
(each payload carries its own as-of / fetched timestamps); the TTL keeps that within minutes.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

MAX_ENTRIES = 64


class ViewCache:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.max_entries = max_entries
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None or item[0] < now:
                if item is not None:
                    del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return item[1]

    def put(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._data), "hits": self.hits, "misses": self.misses}

    async def view(
        self, key: str, ttl: float, build: Callable[[], Awaitable[Any]], keep: Callable[[Any], bool] | None = None
    ):
        """The cached payload for `key`, else build it and keep it for `ttl` seconds when `keep(payload)` allows
        (e.g. not when a source timed out, so a partial answer is not repeated for minutes)."""
        hit = self.get(key)
        if hit is not None:
            return hit
        value = await build()
        if keep is None or keep(value):
            self.put(key, value, ttl)
        return value


VIEWS = ViewCache()

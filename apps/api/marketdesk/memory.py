"""Process memory: measure it, give freed memory back to the system, and track which routes grow it
(docs/PERFORMANCE_ROADMAP.md, phases 0–1).

Render Free stops the container above 512 MB. Python and glibc keep freed memory inside the process, so after a
burst of large responses the resident size stays high; `malloc_trim(0)` returns the free pages. Everything here is
best-effort and a no-op where the platform lacks it (macOS, Windows, musl).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import resource
import sys
import threading
import time

_libc = None
if sys.platform.startswith("linux"):
    try:
        _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        _libc.malloc_trim.argtypes = [ctypes.c_size_t]
    except (OSError, AttributeError):
        _libc = None


def _status_kb(field: str) -> int | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def rss_mb() -> float:
    """Resident memory now, in MB (falls back to the peak where /proc is unavailable)."""
    kb = _status_kb("VmRSS")
    if kb is None:
        return peak_mb()
    return round(kb / 1024, 1)


def peak_mb() -> float:
    kb = _status_kb("VmHWM")
    if kb is None:
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        kb = r // 1024 if sys.platform == "darwin" else r
    return round(kb / 1024, 1)


_trim_lock = threading.Lock()
_last_trim = 0.0


def trim(min_interval: float = 5.0) -> bool:
    """Return free heap pages to the system (glibc only), at most once per `min_interval` seconds."""
    global _last_trim
    if _libc is None:
        return False
    now = time.monotonic()
    with _trim_lock:
        if now - _last_trim < min_interval:
            return False
        _last_trim = now
    try:
        _libc.malloc_trim(0)
        return True
    except Exception:  # noqa: BLE001 - best effort
        return False


class RouteMemory:
    """Bounded table of resident-memory growth per route, to see which pages cost memory."""

    def __init__(self, limit: int = 60):
        self.limit = limit
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def record(self, route: str, grew_mb: float, ms: float) -> None:
        with self._lock:
            row = self._rows.get(route)
            if row is None:
                if len(self._rows) >= self.limit:
                    return
                row = self._rows[route] = {"route": route, "count": 0, "grew_mb": 0.0, "max_grew_mb": 0.0,
                                           "total_ms": 0.0, "max_ms": 0.0}  # fmt: skip
            row["count"] += 1
            row["grew_mb"] = round(row["grew_mb"] + max(0.0, grew_mb), 1)
            row["max_grew_mb"] = round(max(row["max_grew_mb"], grew_mb), 1)
            row["total_ms"] += ms
            row["max_ms"] = round(max(row["max_ms"], ms))

    def top(self, n: int = 10) -> list[dict]:
        with self._lock:
            rows = sorted(self._rows.values(), key=lambda r: (-r["grew_mb"], -r["max_ms"]))[:n]
            return [{**r, "avg_ms": round(r["total_ms"] / r["count"]) if r["count"] else 0} for r in rows]


ROUTES = RouteMemory()

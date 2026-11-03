"""Per-request timing exposed as a `Server-Timing` header (visible in the browser's network panel).

Records total application time, time spent in database round trips, the number of statements and
how many new database connections the request had to open. Contains no data, only durations.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import Engine, event
from sqlalchemy.pool import Pool


@dataclass
class RequestTimings:
    db_ms: float = 0.0
    queries: int = 0
    connects: int = 0


_current: ContextVar[RequestTimings | None] = ContextVar("marketdesk_timings", default=None)
_installed = False


def install_db_listeners() -> None:
    """Attach statement/connection listeners to every engine once per process."""
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        conn.info.setdefault("md_t0", []).append(time.perf_counter())

    @event.listens_for(Engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        stack = conn.info.get("md_t0")
        if not stack:
            return
        elapsed = (time.perf_counter() - stack.pop()) * 1000
        t = _current.get()
        if t is not None:
            t.db_ms += elapsed
            t.queries += 1

    @event.listens_for(Pool, "connect")
    def _connect(dbapi_connection, record):  # noqa: ARG001
        t = _current.get()
        if t is not None:
            t.connects += 1


def start() -> RequestTimings:
    t = RequestTimings()
    _current.set(t)
    return t


def header(t: RequestTimings, app_ms: float) -> str:
    return (
        f'app;dur={app_ms:.1f}, db;dur={t.db_ms:.1f};desc="{t.queries} statements", '
        f'dbconnect;desc="{t.connects} new connections"'
    )

"""The alert worker running inside the web process (docs/DECISIONS.md #77, PERFORMANCE_ROADMAP 2.A).

Render Free gives the whole container 512 MB; a second Python process for the worker cost ~140–170 MB on its own.
Here the same cycle (`marketdesk.worker.__main__.run_cycle`) runs on a background thread with its own event loop,
sharing the web process's market-data cache and SEC client, so no data is held twice.

Exactly one runner: a lease row in app_settings (renewed every cycle) means a second web process — for example the
old and new versions overlapping during a deploy, or a separately started `python -m marketdesk.worker` — waits
instead of evaluating too. Alert events also carry unique keys, so even an overlap could not create duplicates.
Page requests come first: each cycle waits (up to 30 s) for a moment with no API request in flight.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta

from marketdesk import memory
from marketdesk.db import db_session
from marketdesk.models import AppSetting

log = logging.getLogger("marketdesk.worker")
LEASE_KEY = "worker_lease"


def holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire_lease(holder: str, seconds: int, now: datetime | None = None) -> bool:
    """Take or renew the single-runner lease; False while another holder's lease is still valid."""
    now = now or datetime.now(UTC)
    with db_session() as db:
        row = db.get(AppSetting, LEASE_KEY)
        value = row.value if row is not None and isinstance(row.value, dict) else {}
        expires = value.get("expires")
        try:
            valid = expires is not None and datetime.fromisoformat(expires) > now
        except (TypeError, ValueError):
            valid = False
        if valid and value.get("holder") != holder:
            return False
        lease = {"holder": holder, "expires": (now + timedelta(seconds=seconds)).isoformat()}
        if row is None:
            db.add(AppSetting(key=LEASE_KEY, value=lease))
        else:
            row.value = lease
        db.commit()
        return True


def release_lease(holder: str) -> None:
    with db_session() as db:
        row = db.get(AppSetting, LEASE_KEY)
        if row is not None and isinstance(row.value, dict) and row.value.get("holder") == holder:
            db.delete(row)
            db.commit()


class EmbeddedWorker:
    def __init__(self, app_state, settings, start_delay: float = 45.0):
        self.state, self.settings, self.start_delay = app_state, settings, start_delay
        self.holder = holder_id()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at = datetime.now(UTC)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._main, name="alert-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 20.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        try:
            release_lease(self.holder)
        except Exception as exc:  # noqa: BLE001 - shutting down; the lease expires on its own
            log.info("worker lease not released (%s); it expires on its own", type(exc).__name__)

    def _main(self) -> None:
        try:
            # A lower scheduling priority for this thread only (Linux: nice applies per thread), so page requests win.
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except (AttributeError, OSError):
            pass
        asyncio.run(self._loop())

    async def _quiet(self, max_wait: float = 30.0) -> None:
        """Wait for a moment with no API request in flight (pages first), at most `max_wait` seconds."""
        deadline = time.monotonic() + max_wait
        while getattr(self.state, "api_inflight", 0) > 0 and time.monotonic() < deadline and not self._stop.is_set():
            await asyncio.sleep(0.5)

    async def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self._stop.is_set() and time.monotonic() < end:
            await asyncio.sleep(min(1.0, end - time.monotonic()))

    async def _loop(self) -> None:
        from marketdesk.asyncbridge import SHARED_EXECUTOR
        from marketdesk.worker.__main__ import mark_started, run_cycle

        asyncio.get_running_loop().set_default_executor(SHARED_EXECUTOR)
        poll = max(30, int(self.settings.alert_poll_seconds))
        await self._sleep(self.start_delay)  # let the site answer first after a start
        marked = False
        while not self._stop.is_set():
            try:
                if await asyncio.to_thread(acquire_lease, self.holder, poll * 3):
                    if not marked:
                        await asyncio.to_thread(mark_started, self.state.market.source)
                        marked = True
                    await self._quiet()
                    summary = await run_cycle(self.state.market, self.state.research, embedded=True)
                    log.info("cycle: %s", {k: v for k, v in summary.items() if k != "skipped"})
                else:
                    log.info("another process holds the worker lease; waiting")
            except Exception:  # never let the background loop die
                log.exception("embedded worker cycle failed")
            memory.trim(min_interval=0)
            await self._sleep(poll)

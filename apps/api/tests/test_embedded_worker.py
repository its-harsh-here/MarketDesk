"""Embedded alert worker (DECISIONS #77): one runner via a lease (a second holder waits until expiry; the holder
renews), the cycle runs inside the app with the shared market service and reports memory as embedded."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from marketdesk.worker.embedded import EmbeddedWorker, acquire_lease, release_lease


def test_lease_has_one_holder_until_it_expires(app):
    t0 = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
    assert acquire_lease("web-a", 90, t0)
    assert not acquire_lease("web-b", 90, t0 + timedelta(seconds=30))  # another process waits
    assert acquire_lease("web-a", 90, t0 + timedelta(seconds=60))  # the holder renews
    assert acquire_lease("web-b", 90, t0 + timedelta(seconds=200))  # expired: taken over
    release_lease("web-a")  # not the holder: no effect
    assert not acquire_lease("web-a", 90, t0 + timedelta(seconds=210))
    release_lease("web-b")
    assert acquire_lease("web-a", 90, t0 + timedelta(seconds=220))
    release_lease("web-a")


def test_embedded_cycle_runs_in_the_app_and_reports(app, api):
    w = EmbeddedWorker(app.state, app.state.settings, start_delay=0)
    from marketdesk.worker.__main__ import run_cycle

    summary = asyncio.run(run_cycle(app.state.market, app.state.research, embedded=True))
    assert summary["memory"]["embedded"] is True and summary["memory"]["rss_mb"] > 0
    st = api.get("/api/status").json()
    assert (
        st["worker"]["running"] is True and st["memory"]["embedded_worker"] is True and st["memory"]["worker"] is None
    )
    assert w.holder.endswith(str(__import__("os").getpid()))

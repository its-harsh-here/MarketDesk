"""Round-trip and event-loop behaviour that keeps the hosted site responsive (database in another
region, 0.1 CPU). These guard against regressions that only show up as latency in production."""

from __future__ import annotations

import asyncio
import re
import time

import pytest
from sqlalchemy import exc

from marketdesk.asyncbridge import off_event_loop, run_on_home_loop
from marketdesk.db import IDLE_PING_SECONDS, _ping_if_idle, db_session
from marketdesk.models import AppSetting
from marketdesk.services import auth
from marketdesk.services.prefs import get_prefs, update_prefs
from tests.conftest import OWNER_PW


def _statements(response) -> int:
    m = re.search(r'db;dur=[\d.]+;desc="(\d+) statements"', response.headers["server-timing"])
    assert m, response.headers.get("server-timing")
    return int(m.group(1))


def _login(api):
    r = api.post("/api/auth/login", json={"username": "owner", "password": OWNER_PW})
    assert r.status_code == 200
    api.csrf = r.json()["csrf_token"]


def test_server_timing_header_on_api_responses(owner_api):
    api, _ = owner_api
    r = api.get("/api/health")
    assert r.headers["server-timing"].startswith("app;dur=")
    assert _statements(r) == 0


def test_authenticated_reads_do_not_query_revocations_every_time(owner_api):
    api, _ = owner_api
    _login(api)
    api.get("/api/auth/session")
    assert _statements(api.get("/api/auth/session")) == 0  # revocation state served from the short cache
    assert _statements(api.get("/api/settings")) <= 2  # preferences + default-watchlist check


def test_revocation_written_elsewhere_applies_after_cache_window(owner_api, monkeypatch):
    api, _ = owner_api
    _login(api)
    assert api.get("/api/watchlists").status_code == 200
    now = [1000.0]
    monkeypatch.setattr(auth, "_clock", lambda: now[0])
    auth.clear_revocation_cache()
    assert api.get("/api/watchlists").status_code == 200  # caches the current (empty) revocation state
    # Another process (the CLI) sets the "sign out everywhere" epoch without touching this cache.
    with db_session() as db:
        db.merge(AppSetting(key="sessions_valid_after", value=int(time.time()) + 5))
        db.commit()
    assert api.get("/api/watchlists").status_code == 200  # still inside the cache window
    now[0] += auth.REVOCATION_CACHE_SECONDS + 1
    assert api.get("/api/watchlists").status_code == 401


def test_sign_out_takes_effect_immediately_despite_cache(owner_api):
    api, _ = owner_api
    _login(api)
    token = api.c.cookies.get("md_session")
    assert api.get("/api/watchlists").status_code == 200
    assert api.post("/api/auth/logout").status_code in (200, 204)
    api.c.cookies.set("md_session", token)
    assert api.get("/api/watchlists").status_code == 401


def test_offloaded_handler_keeps_the_server_loop_free():
    seen = {}

    async def market_call():
        seen["loop"] = asyncio.get_running_loop()
        return 41

    @off_event_loop
    async def handler(x):
        time.sleep(0.3)  # a blocking database round trip
        return x + await run_on_home_loop(market_call)

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(ticker())
        result = await handler(1)
        t.cancel()
        return result, ticks, asyncio.get_running_loop()

    result, ticks, loop = asyncio.run(main())
    assert result == 42
    assert ticks >= 10  # the server loop kept serving while the handler blocked
    assert seen["loop"] is loop  # market data still runs on the server loop (shared cache, de-dup)


class _Cursor:
    def __init__(self, fail):
        self.fail = fail
        self.executed = []

    def execute(self, sql):
        if self.fail:
            raise OSError("server closed the connection")
        self.executed.append(sql)

    def close(self):
        pass


class _Conn:
    def __init__(self, fail=False):
        self.autocommit = False
        self.cur = _Cursor(fail)

    def cursor(self):
        return self.cur


class _Record:
    def __init__(self, idle_for):
        self.info = {"md_idle_since": time.monotonic() - idle_for}


def test_busy_connections_are_not_pinged():
    conn = _Conn()
    _ping_if_idle(conn, _Record(idle_for=1), None)
    assert conn.cur.executed == []


def test_idle_connections_are_pinged_outside_a_transaction():
    conn = _Conn()
    _ping_if_idle(conn, _Record(idle_for=IDLE_PING_SECONDS + 1), None)
    assert conn.cur.executed == ["SELECT 1"]
    assert conn.autocommit is False  # restored


def test_dead_idle_connection_is_replaced():
    with pytest.raises(exc.DisconnectionError):
        _ping_if_idle(_Conn(fail=True), _Record(idle_for=IDLE_PING_SECONDS + 1), None)


def test_preferences_are_read_once_per_request_and_refreshed_after_writes(app):
    with db_session() as db:
        assert get_prefs(db)["theme"] == "dark"
        update_prefs(db, {"theme": "light"})
        assert get_prefs(db)["theme"] == "light"

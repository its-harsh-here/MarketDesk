"""Assembled-view cache (PERFORMANCE_ROADMAP 3.4): bounded, expires, skips partial answers, cleared by any change."""

import asyncio
import time

from marketdesk.services.viewcache import VIEWS, ViewCache


def test_bounded_and_expiring(monkeypatch):
    c = ViewCache(max_entries=2)
    c.put("a", 1, 60)
    c.put("b", 2, 60)
    c.put("c", 3, 60)
    assert c.get("a") is None and c.get("c") == 3  # oldest dropped
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + 61)
    assert c.get("c") is None


def test_partial_answers_are_not_kept():
    c = ViewCache()
    calls = []

    async def build():
        calls.append(1)
        return {"complete": len(calls) > 1}

    async def run():
        await c.view("k", 60, build, keep=lambda v: v["complete"])
        await c.view("k", 60, build, keep=lambda v: v["complete"])  # rebuilt: the first was partial
        return await c.view("k", 60, build, keep=lambda v: v["complete"])  # now cached

    assert asyncio.run(run()) == {"complete": True} and len(calls) == 2


def test_any_change_by_the_user_clears_cached_views(api):
    api.get("/api/terminal/risk", params={"symbol": "SX:AURORA"})
    assert VIEWS.stats()["entries"] >= 1
    assert api.get("/api/status").json()["memory"]["views"]["entries"] >= 1
    api.post("/api/watchlists", json={"name": "Clears views"})
    assert VIEWS.stats()["entries"] == 0

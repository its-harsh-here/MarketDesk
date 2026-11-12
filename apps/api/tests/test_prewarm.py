"""Pre-warming (PERFORMANCE_ROADMAP 3.1): watchlist and holdings symbols round-robin a few per cycle through the
market service (fresh entries are not fetched again), and the macro watchboard is warmed too."""

from __future__ import annotations

import asyncio

from marketdesk.db import db_session
from marketdesk.services import prewarm


def test_round_robin_over_watchlist_symbols(app, api):
    wl = api.post("/api/watchlists", json={"name": "Warm"}).json()
    for s in ("SX:AURORA", "SX:BANYAN", "SX:ELARA"):
        api.post(f"/api/watchlists/{wl['id']}/items", json={"symbol": s})
    market = app.state.market
    prewarm._cursor["i"] = 0
    with db_session() as db:
        assert prewarm.symbols(db, market.source) == ["SX:AURORA", "SX:BANYAN", "SX:ELARA"]
        first = asyncio.run(prewarm.warm(db, market, per_cycle=2))
        second = asyncio.run(prewarm.warm(db, market, per_cycle=2))
    assert first["warmed"] == ["SX:AURORA", "SX:BANYAN"] and second["warmed"] == ["SX:ELARA", "SX:AURORA"]
    assert first["failed"] == 0 and first["macro"]["watchboard"] == "ok"

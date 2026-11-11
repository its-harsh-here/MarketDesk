"""Watchlist key figures come from stored screening snapshots only: null until loaded, values after a refresh."""

from __future__ import annotations

from .test_m06 import refresh


def test_watchlist_metrics_read_stored_snapshots(api):
    wl = api.post("/api/watchlists", json={"name": "K"}).json()["id"]
    for s in ("SX:AURORA", "SX:BANYAN"):
        api.post(f"/api/watchlists/{wl}/items", json={"symbol": s})
    before = api.get(f"/api/watchlists/{wl}/metrics").json()
    assert set(before["items"]) == {"SX:AURORA", "SX:BANYAN"} and before["items"]["SX:AURORA"] is None
    refresh(api, {"kind": "watchlist", "id": wl})
    after = api.get(f"/api/watchlists/{wl}/metrics").json()["items"]["SX:AURORA"]
    assert after is not None and after["stale"] is False
    assert after["market_cap"]["v"] is not None and after["pe_ratio"]["v"] is not None
    assert after["from_52w_high_pct"]["v"] is not None and float(after["from_52w_high_pct"]["v"]) <= 0
    assert api.get("/api/watchlists/999999/metrics").status_code == 404

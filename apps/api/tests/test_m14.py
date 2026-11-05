"""M14: workspace presets persist and apply, owner quotas only tighten server caps, usage counters, research export
with private sections off by default, refresh preference."""

from __future__ import annotations


def test_workspaces_persist_apply_and_validate(api):
    ws = api.get("/api/workspaces").json()
    assert [w["id"] for w in ws["items"]] == ["market", "research", "portfolio"] and ws["active"] is None
    wl = api.post("/api/watchlists", json={"name": "Focus"}).json()
    created = api.post(
        "/api/workspaces",
        json={
            "name": "Mornings",
            "start": "/watchlists",
            "density": "compact",
            "default_watchlist_id": wl["id"],
            "chart_symbol": "SX:AURORA",
        },  # fmt: skip
    )
    assert created.status_code == 201, created.text
    w = created.json()
    assert api.post("/api/workspaces", json={"name": "mornings", "start": "/"}).status_code == 409
    assert api.post("/api/workspaces", json={"name": "X", "start": "/api/backup"}).status_code == 422
    applied = api.post(f"/api/workspaces/{w['id']}/apply").json()
    assert applied["prefs"]["density"] == "compact" and applied["prefs"]["default_watchlist_id"] == wl["id"]
    assert applied["prefs"]["chart_symbol"] == "SX:AURORA" and applied["notes"] == []
    assert api.get("/api/workspaces").json()["active"] == w["id"]  # survives a reload
    assert api.get("/api/settings").json()["density"] == "compact"
    # "Save current layout" captures the current preferences
    cap = api.post("/api/workspaces", json={"name": "Snapshot", "start": "/lab", "capture": True}).json()
    assert cap["density"] == "compact" and cap["default_watchlist_id"] == wl["id"]
    # a deleted watchlist is reported, not silently re-created
    api.delete(f"/api/watchlists/{wl['id']}")
    again = api.post(f"/api/workspaces/{w['id']}/apply").json()
    assert again["notes"] and again["prefs"]["default_watchlist_id"] is None
    for x in api.get("/api/workspaces").json()["items"][:-1]:
        assert api.delete(f"/api/workspaces/{x['id']}").status_code == 204
    last = api.get("/api/workspaces").json()["items"]
    assert len(last) == 1 and api.delete(f"/api/workspaces/{last[0]['id']}").status_code == 409


def test_refresh_preference(api):
    assert api.get("/api/settings").json()["quote_refresh_seconds"] == 60
    assert api.patch("/api/settings", json={"quote_refresh_seconds": 0}).json()["quote_refresh_seconds"] == 0
    assert api.patch("/api/settings", json={"quote_refresh_seconds": 45}).status_code == 422


def test_usage_counts_requests_and_quotas_only_tighten(api):
    api.get("/api/market/snapshots", params={"symbols": "SX:AURORA"})
    api.get("/api/market/snapshots", params={"symbols": "SX:AURORA"})
    u = api.get("/api/usage").json()
    q = u["provider"]["by_kind"]["quote"]
    assert q["requests"] >= 2 and q["cache_hits"] >= 1 and q["upstream_calls"] >= 1
    assert u["provider"]["cache_ttl_seconds"]["quote"] > 0 and "endpoints" in u["provider"]
    caps = u["ai"]["server_caps"]
    assert u["ai"]["budget"]["requests_limit"] == caps["requests"]
    bad = api.put("/api/usage/quotas", json={"requests": caps["requests"] + 1})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "above_server_cap"
    ok = api.put("/api/usage/quotas", json={"requests": 3, "tokens": None, "usd": None})
    assert ok.status_code == 200, ok.text
    u = api.get("/api/usage").json()
    assert u["ai"]["budget"]["requests_limit"] == 3 and u["ai"]["owner_quotas"]["requests"] == 3


def test_quota_is_enforced_at_reservation(app):
    from datetime import UTC, datetime
    from decimal import Decimal

    from marketdesk.db import db_session
    from marketdesk.models import AiAnswer, AppSetting

    analyst = app.state.analyst
    with db_session() as db:
        db.add(AppSetting(key="ai_quotas", value={"requests": 0, "tokens": None, "usd": None}))
        db.commit()
        a = AiAnswer(day=datetime.now(UTC).date(), kind="ask", symbols=["SX:AURORA"], question="q", status="running")
        db.add(a)
        db.commit()
        reason = analyst.reserve(db, a, Decimal("0.001"), tokens=10)
        assert reason and "Daily request limit reached (0" in reason


def test_research_export_private_sections_off_by_default(api):
    api.post("/api/journal", json={"symbol": "SX:AURORA", "entry_date": "2026-01-02", "title": "Private thesis"})
    api.post("/api/portfolio/transactions", json={"type": "DEPOSIT", "effective_date": "2026-01-02", "amount": "10000"})
    api.post(
        "/api/portfolio/transactions",
        json={"type": "BUY", "effective_date": "2026-01-05", "symbol": "SX:AURORA", "quantity": "3", "price": "100"},
    )
    r = api.get("/api/export/research", params={"symbol": "SX:AURORA"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/markdown") and "attachment" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    md = r.text
    assert "**Private sections included:** none." in md and "Private thesis" not in md and "## Holding" not in md
    assert "## Last observed quote" in md and "source fixture" in md and "## Fundamentals" in md
    assert "Saved AI research" in md and "No saved answers" in md
    full = api.get("/api/export/research", params={"symbol": "SX:AURORA", "include": "journal,holdings"}).text
    assert "**Private sections included:** journal, holdings." in full and "Private thesis" in full
    assert "| Quantity | 3.0000 |" in full and "Saved AI research" not in full
    assert api.get("/api/export/research", params={"symbol": "SX:AURORA", "include": "secrets"}).status_code == 422


def test_export_and_usage_need_sign_in(owner_api):
    a, _ = owner_api
    assert a.get("/api/export/research", params={"symbol": "SX:AURORA"}).status_code == 401
    assert a.get("/api/usage").status_code == 401 and a.get("/api/workspaces").status_code == 401

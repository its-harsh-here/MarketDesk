"""API integration tests in fixture mode: watchlists, ledger, briefing, routing."""

from __future__ import annotations


def deposit(api, amount="10000", day="2026-01-02"):
    return api.post("/api/portfolio/transactions", json={"type": "DEPOSIT", "effective_date": day, "amount": amount})


def trade(api, type_, qty, price, fees="0", day="2026-01-05", symbol="SX:AURORA"):
    return api.post(
        "/api/portfolio/transactions",
        json={"type": type_, "effective_date": day, "symbol": symbol, "quantity": qty, "price": price, "fees": fees},
    )


def test_watchlist_crud_and_persistence(api):
    r = api.post("/api/watchlists", json={"name": "  Core   ideas "})
    assert r.status_code == 201
    wid = r.json()["id"]
    assert r.json()["name"] == "Core ideas"
    assert api.post("/api/watchlists", json={"name": "Core ideas"}).status_code == 409
    for sym in ("SX:AURORA", "banyan", "SX:SX50"):
        assert api.post(f"/api/watchlists/{wid}/items", json={"symbol": sym}).status_code == 201
    dup = api.post(f"/api/watchlists/{wid}/items", json={"symbol": "SX:AURORA"})
    assert dup.status_code == 409
    bad = api.post(f"/api/watchlists/{wid}/items", json={"symbol": "RELIANCE.NS"})
    assert bad.status_code == 422 and "fixture" in bad.json()["error"]["message"].lower()
    order = api.put(f"/api/watchlists/{wid}/order", json={"symbols": ["SX:SX50", "SX:AURORA", "SX:BANYAN"]})
    assert [i["symbol"] for i in order.json()["items"]] == ["SX:SX50", "SX:AURORA", "SX:BANYAN"]
    api.patch(f"/api/watchlists/{wid}", json={"sort_key": "change_percent", "sort_dir": "desc", "name": "Renamed"})
    got = api.get(f"/api/watchlists/{wid}").json()
    assert got["name"] == "Renamed" and got["sort_key"] == "change_percent" and got["sort_dir"] == "desc"
    assert api.get("/api/watchlists/membership", params={"symbol": "SX:AURORA"}).json()["watchlist_ids"] == [wid]
    assert api.delete(f"/api/watchlists/{wid}/items", params={"symbol": "SX:AURORA"}).status_code == 200
    assert api.get("/api/settings").json()["default_watchlist_id"] == wid
    assert api.delete(f"/api/watchlists/{wid}").status_code == 204
    assert api.get(f"/api/watchlists/{wid}").status_code == 404
    assert api.get("/api/settings").json()["default_watchlist_id"] is None


def test_snapshot_reports_missing_quote_without_zero(api):
    rows = api.get("/api/market/snapshots", params={"symbols": "SX:QUILL,SX:AURORA"}).json()
    quill = next(r for r in rows if r["symbol"] == "SX:QUILL")
    assert quill["quote"] is None
    assert quill["meta"]["status"] == "missing"
    assert "suspended" in quill["meta"]["message"].lower()
    aurora = next(r for r in rows if r["symbol"] == "SX:AURORA")
    assert aurora["meta"]["status"] == "sample"
    assert aurora["meta"]["market_time"] == "2026-06-30T10:00:00Z"  # fixed dataset time, never "now"
    assert aurora["quote"]["last_price"] == "169.8"
    # last price and previous close come from the same series
    assert aurora["quote"]["previous_close"] == aurora["sparkline"][-2]["close"]


def test_history_is_ascending_and_unique(api):
    data = api.get("/api/market/history", params={"symbol": "SX:ELARA", "range": "5Y"}).json()
    dates = [b["time"] for b in data["bars"]]
    assert dates == sorted(dates) and len(dates) == len(set(dates))
    assert data["supported_ranges"] == ["1M", "3M", "6M", "1Y", "5Y"]
    assert "adjusted" in data["adjustment"]
    assert api.get("/api/market/history", params={"symbol": "SX:ELARA", "range": "2Y"}).status_code == 422


def test_ledger_acceptance_via_api(api):
    assert deposit(api).status_code == 201
    assert trade(api, "BUY", "10", "100", "10", day="2026-01-03").status_code == 201
    assert trade(api, "BUY", "10", "120", "10", day="2026-01-04").status_code == 201
    r = trade(api, "SELL", "5", "130", "5", day="2026-01-05")
    assert r.status_code == 201
    body = r.json()
    assert body["realized_pnl"] == "90" and body["cash_after"] == "8425"
    s = api.get("/api/portfolio/summary").json()
    assert s["cash"] == "8425" and s["realized_pnl"] == "90"
    h = s["holdings"][0]
    assert h["quantity"] == "15" and h["cost_basis"] == "1665" and h["average_cost"] == "111"
    # Valued at the sample mark (169.80), never zero
    assert h["market_value"] == "2547" and s["complete"] is True


def test_ledger_rejects_oversell_and_negative_cash_with_reason(api):
    deposit(api, "1000")
    r = trade(api, "BUY", "20", "100")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ledger_rejected"
    assert "negative" in r.json()["error"]["message"]
    trade(api, "BUY", "5", "100")
    r = trade(api, "SELL", "6", "100", day="2026-01-06")
    assert r.status_code == 422 and "only 5" in r.json()["error"]["message"]


def test_historical_edit_and_delete_replay(api):
    dep = deposit(api, "1000").json()
    buy = trade(api, "BUY", "5", "100").json()
    # editing the deposit below the buy cost is rejected and leaves data unchanged
    r = api.put(
        f"/api/portfolio/transactions/{dep['id']}",
        json={"type": "DEPOSIT", "effective_date": "2026-01-02", "amount": "100"},
    )
    assert r.status_code == 422
    assert api.get("/api/portfolio/summary").json()["cash"] == "500"
    # deleting the deposit is rejected because the buy would overdraw
    assert api.delete(f"/api/portfolio/transactions/{dep['id']}").status_code == 422
    ok = api.put(
        f"/api/portfolio/transactions/{buy['id']}",
        json={"type": "BUY", "effective_date": "2026-01-05", "symbol": "SX:AURORA", "quantity": "2", "price": "100"},
    )
    assert ok.status_code == 200 and ok.json()["created_at"] == buy["created_at"]
    assert api.get("/api/portfolio/summary").json()["cash"] == "800"


def test_split_requires_explicit_confirmation(api):
    deposit(api, "1000")
    trade(api, "BUY", "5", "100")
    payload = {
        "type": "SPLIT",
        "effective_date": "2026-01-07",
        "symbol": "SX:AURORA",
        "split_from": "1",
        "split_to": "2",
    }
    r = api.post("/api/portfolio/transactions", json=payload)
    assert r.status_code == 422 and r.json()["error"]["code"] == "split_unconfirmed"
    r = api.post("/api/portfolio/transactions", json={**payload, "split_confirmed": True})
    assert r.status_code == 201
    h = api.get("/api/portfolio/summary").json()["holdings"][0]
    assert h["quantity"] == "10" and h["cost_basis"] == "500" and h["average_cost"] == "50"


def test_usd_listing_never_enters_the_inr_account_and_index_cannot_be_held(api):
    deposit(api)
    r = trade(api, "BUY", "1", "10", symbol="SX:HALCYON")  # a USD listing, recorded against the INR account
    assert r.status_code == 422 and r.json()["error"]["code"] == "currency_mismatch"
    assert "Record it in the USD account" in r.json()["error"]["message"]
    r = trade(api, "BUY", "1", "10", symbol="SX:SX50")
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_holdable"
    r = trade(api, "BUY", "1", "10", symbol="SX:USDINR")
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_holdable"


def test_missing_mark_makes_valuation_incomplete(api):
    deposit(api)
    assert trade(api, "BUY", "1", "200", symbol="SX:QUILL", day="2026-01-05").status_code == 201
    s = api.get("/api/portfolio/summary").json()
    assert s["complete"] is False and s["total_equity"] is None
    assert s["missing_marks"] == ["SX:QUILL"]
    assert s["holdings"][0]["market_value"] is None and s["holdings"][0]["mark_status"] == "missing"


def test_briefing_uses_rules_not_causes(api):
    api.post("/api/workspace/starter-watchlist")
    items = api.get("/api/briefing").json()["items"]
    moves = [i for i in items if i["kind"] == "move"]
    assert len(moves) == 3
    for m in moves:
        assert " because " not in m["text"].lower() and "buy" not in m["text"].lower()


def test_unknown_api_route_is_json_404(api):
    r = api.get("/api/definitely-not-here")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = api.post("/api/definitely-not-here")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_prefs_validation(api):
    assert api.patch("/api/settings", json={"display_timezone": "Mars/Base"}).status_code == 422
    r = api.patch("/api/settings", json={"theme": "light", "density": "compact", "chart_symbol": "elara"})
    assert r.json()["theme"] == "light" and r.json()["chart_symbol"] == "SX:ELARA"


def test_sample_portfolio_endpoint_removed(api):
    r = api.post("/api/workspace/sample-portfolio")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"

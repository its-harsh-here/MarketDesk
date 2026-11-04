"""M06: declared universes, normalized snapshot, filters that never pass missing values, saved screens, export,
peers and the sector heatmap."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from marketdesk.providers.base import (
    AnnualPeriod,
    AnnualStatements,
    DailyBar,
    Fundamentals,
    InstrumentRef,
    PriceHistory,
    ProviderError,
)
from marketdesk.services.market import DataMeta, Result
from marketdesk.services.screener import compute_snapshot, evaluate, validate_filters

REF = InstrumentRef("SX:TEST", "Test Co", "SAMPLEX", "INR", "Asia/Kolkata", "EQUITY")
NOW = datetime(2026, 6, 30, 10, tzinfo=UTC)


def ok(value, status="available"):
    return Result(value, DataMeta(source="fixture", status=status, fetched_at=NOW))


def gone(status="unavailable", message="Upstream down."):
    return Result(None, DataMeta(source="fixture", status=status, message=message))


def bars(n: int, start=Decimal(100), step=Decimal("0.5"), volume: int | None = 1000, end=date(2026, 6, 30)):
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    out = []
    for i, day in enumerate(days):
        c = start + step * i + (Decimal(1) if i % 2 else Decimal(0))  # zig-zag so volatility is non-zero
        out.append(DailyBar(day, c, c + 1, c - 1, c, volume))
    return out


def fund(**over):
    base = dict(
        instrument=REF,
        market_cap=Decimal(5_000_000_000),
        pe_ratio=Decimal("18.5"),
        dividend_yield_percent=None,
        fifty_two_week_high=None,
        fifty_two_week_low=None,
        price_to_book=Decimal("2.1"),
        sector="Industrials",
        industry="Machinery",
        last_fiscal_year_end=None,
        most_recent_quarter=None,
        notes=[],
    )
    base.update(over)
    return Fundamentals(**base)


def stmts(*periods):
    return AnnualStatements(REF, list(periods), "Test statements", [])


def test_snapshot_values_units_and_reasons():
    bs = bars(260)
    hist = ok(PriceHistory(REF, "1Y", bs, "Split-adjusted"))
    p0 = AnnualPeriod(date(2026, 3, 31), Decimal(1200), Decimal(120), Decimal(300), Decimal(600))
    p1 = AnnualPeriod(date(2025, 3, 31), Decimal(1000), Decimal(90), Decimal(250), Decimal(560))
    snap = compute_snapshot("EQUITY", gone(), hist, ok(fund()), ok(stmts(p0, p1)))
    # quote unavailable: explained, never zero
    assert snap["last_price"] == {"v": None, "why": "Upstream down.", "as_of": None}
    # returns from the last close on or before the target date
    last = bs[-1]
    one_m = [b for b in bs if b.session_date <= date(2026, 5, 30)][-1]
    assert Decimal(snap["return_1m_pct"]["v"]) == ((last.close / one_m.close - 1) * 100).quantize(Decimal("0.01"))
    assert snap["return_1m_pct"]["from"] == one_m.session_date.isoformat()
    # the first close within 5 days after the target date is used, and named, when history starts just after it
    assert snap["return_1y_pct"]["v"] is not None and snap["return_1y_pct"]["from"] == bs[0].session_date.isoformat()
    assert bs[0].session_date - date(2025, 6, 30) <= timedelta(days=5)
    short = compute_snapshot("EQUITY", None, ok(PriceHistory(REF, "1Y", bars(200), "x")), None, None)
    assert short["return_1y_pct"]["v"] is None and "starts" in short["return_1y_pct"]["why"]  # no silent shortening
    assert short["volatility_1y_pct"]["v"] is not None and short["volatility_1y_pct"]["n"] == 199
    # volume window excludes the latest (possibly incomplete) bar
    assert snap["avg_volume_20d"]["v"] == "1000" and snap["avg_volume_20d"]["as_of"] == bs[-2].session_date.isoformat()
    window = bs[-21:-1]
    assert Decimal(snap["avg_value_20d"]["v"]) == (sum(b.close * 1000 for b in window) / 20).quantize(Decimal(1))
    assert Decimal(snap["volatility_1y_pct"]["v"]) > 0 and snap["volatility_1y_pct"]["n"] == 252
    assert Decimal(snap["from_52w_high_pct"]["v"]) <= 0
    # valuation as reported; missing dividend yield explained
    assert snap["pe_ratio"]["v"] == "18.50" and snap["market_cap"]["v"] == "5000000000"
    assert snap["dividend_yield_pct"]["v"] is None and "dividends" in snap["dividend_yield_pct"]["why"]
    # statement ratios
    assert snap["revenue_growth_pct"]["v"] == "20.00" and snap["revenue_growth_pct"]["from"] == "2025-03-31"
    assert snap["net_margin_pct"]["v"] == "10.00" and snap["roe_pct"]["v"] == "20.00"
    assert snap["debt_to_equity"]["v"] == "0.50" and snap["debt_to_equity"]["as_of"] == "2026-03-31"
    assert snap["sector"] == "Industrials" and snap["_inputs"]["quote"]["status"] == "unavailable"


def test_snapshot_leverage_and_profitability_edge_cases():
    p0 = AnnualPeriod(date(2026, 3, 31), Decimal(500), Decimal(-40), None, Decimal(-10))
    s = compute_snapshot("EQUITY", None, None, ok(fund()), ok(stmts(p0)))
    assert s["revenue_growth_pct"]["why"] == "No prior fiscal year to compare."
    assert s["net_margin_pct"]["v"] == "-8.00"  # a loss is a real negative margin, not missing
    assert "zero or negative" in s["roe_pct"]["why"] and s["debt_to_equity"]["v"] is None
    bank = compute_snapshot(
        "EQUITY",
        None,
        None,
        ok(fund(sector="Financial Services")),
        ok(stmts(AnnualPeriod(date(2026, 3, 31), Decimal(9), Decimal(2), Decimal(80), Decimal(10)))),
    )
    assert bank["debt_to_equity"]["v"] is None and "banks" in bank["debt_to_equity"]["why"]
    assert bank["roe_pct"]["v"] == "20.00"
    idx = compute_snapshot("INDEX", None, None, None, None)
    assert "index" in idx["pe_ratio"]["why"] and "index" in idx["roe_pct"]["why"]


def test_missing_never_passes_and_currency_comparisons_state_the_rate():
    class Inst:
        currency, country, exchange = "USD", "US", "NYSE"

    snap = {"market_cap": {"v": "1000000000"}, "pe_ratio": {"v": None, "why": "Negative earnings."}}
    (f_pe,) = validate_filters([{"metric": "pe_ratio", "op": "lte", "value": "25"}])
    assert evaluate(Inst, snap, f_pe, {}) == ("missing", "Negative earnings.")
    (f_cap,) = validate_filters([{"metric": "market_cap", "op": "gte", "value": "50000000000", "currency": "INR"}])
    assert evaluate(Inst, snap, f_cap, {})[0] == "missing"  # no rate: not comparable, not a pass
    assert evaluate(Inst, snap, f_cap, {("USD", "INR"): Decimal(84)})[0] == "pass"  # 84 bn INR ≥ 50 bn
    assert evaluate(Inst, snap, f_cap, {("USD", "INR"): Decimal(40)})[0] == "fail"
    (f_mkt,) = validate_filters([{"metric": "country", "op": "in", "values": ["IN"]}])
    assert evaluate(Inst, snap, f_mkt, {})[0] == "fail"
    with pytest.raises(Exception, match="currency"):
        validate_filters([{"metric": "market_cap", "op": "gte", "value": "1"}])
    with pytest.raises(Exception, match="upper bound"):
        validate_filters([{"metric": "pe_ratio", "op": "between", "value": "30", "value2": "10"}])
    with pytest.raises(Exception, match="unknown metric"):
        validate_filters([{"metric": "eps_magic", "op": "gte", "value": "1"}])


def test_yahoo_statement_frames():
    pd = pytest.importorskip("pandas")
    from marketdesk.providers.yahoo import statements_from_frames

    cols = [pd.Timestamp("2025-03-31"), pd.Timestamp("2024-03-31")]
    income = pd.DataFrame(
        {cols[0]: [1200.0, 120.0], cols[1]: [1000.0, float("nan")]}, index=["TotalRevenue", "NetIncome"]
    )
    balance = pd.DataFrame(
        {cols[0]: [300.0, 600.0], cols[1]: [250.0, 560.0]}, index=["TotalDebt", "StockholdersEquity"]
    )
    st = statements_from_frames("ABC.NS", income, balance)
    assert [p.period_end for p in st.periods] == [date(2025, 3, 31), date(2024, 3, 31)]
    assert st.periods[0].revenue == Decimal("1200.0") and st.periods[1].net_income is None  # NaN is missing, not 0
    with pytest.raises(ProviderError):
        statements_from_frames("ABC.NS", pd.DataFrame(), pd.DataFrame())


# ------------------------------------------------------------------------------------------------- API (fixture data)
def watchlist(api, name, symbols):
    wid = api.post("/api/watchlists", json={"name": name}).json()["id"]
    for s in symbols:
        assert api.post(f"/api/watchlists/{wid}/items", json={"symbol": s}).status_code == 201
    return wid


def refresh(api, universe):
    r = api.post("/api/screener/refresh", json={"universe": universe})
    assert r.status_code == 202, r.text
    for _ in range(200):
        st = api.get("/api/screener/refresh").json()
        if not st["running"]:
            return st
        time.sleep(0.05)
    raise AssertionError("refresh did not finish")


def run(api, universe, filters=(), sort=None):
    r = api.post("/api/screener/run", json={"universe": universe, "filters": list(filters), "sort": sort})
    assert r.status_code == 200, r.text
    return r.json()


SYMS = ["SX:AURORA", "SX:DELTAFIN", "SX:GLASSWING", "SX:NIMBUS", "SX:HALCYON", "SX:HELIX", "SX:SX50"]


def test_screen_flow_universe_snapshot_filters_sort_and_export(api):
    wid = watchlist(api, "Screen me", SYMS)
    uni = {"kind": "watchlist", "id": wid}
    opts = api.get("/api/screener/universes").json()["options"]
    assert {"kind": "watchlist", "id": wid, "label": "Watchlist · Screen me", "count": 7} in opts

    before = run(api, uni, [{"metric": "pe_ratio", "op": "lte", "value": "40"}])
    assert before["universe"]["excluded"] == ["SX:SX50"]  # indices are not screened, and the result says so
    assert before["dataset"]["loaded"] == 0 and before["matched"] == 0
    assert before["funnel"][0]["missing"] == 6  # nothing loaded yet: missing, never a pass

    st = refresh(api, uni)
    assert st["result"]["refreshed"] == 6 and st["result"]["failed"] == []

    res = run(api, uni, [{"metric": "pe_ratio", "op": "lte", "value": "40"}], {"key": "pe_ratio", "dir": "asc"})
    assert res["dataset"]["loaded"] == 6 and res["dataset"]["not_loaded"] == []
    f = res["funnel"][0]
    assert f["missing"] == 1  # NIMBUS: negative earnings, so no P/E
    assert f["passed"] + f["failed"] + f["missing"] == 6
    pes = [Decimal(r["metrics"]["pe_ratio"]["v"]) for r in res["rows"]]
    assert pes == sorted(pes) and all(p <= 40 for p in pes)
    aurora = next(r for r in res["rows"] if r["symbol"] == "SX:AURORA")
    assert aurora["metrics"]["pe_ratio"]["v"] == "11.96" and aurora["sector"] == "Utilities"
    assert aurora["metrics"]["roe_pct"]["v"] == "14.79" and aurora["metrics"]["debt_to_equity"]["v"] == "1.35"
    assert res["coverage"]["pe_ratio"] == {**res["coverage"]["pe_ratio"], "with_value": 5, "members": 6}

    lev = run(api, uni, [{"metric": "debt_to_equity", "op": "lte", "value": "10"}])
    assert "SX:DELTAFIN" not in [r["symbol"] for r in lev["rows"]]  # a lender's leverage is not meaningful
    assert lev["funnel"][0]["missing"] >= 2  # DELTAFIN (lender), NIMBUS (no equity), HELIX (no statements)

    # USD listing compared with an INR amount at the stated sample rate
    cap = run(api, uni, [{"metric": "market_cap", "op": "gte", "value": "1", "currency": "INR"}])
    assert "SX:HALCYON" in [r["symbol"] for r in cap["rows"]] and cap["fx"]["pair"] == "USD/INR"

    # sorting puts missing values last in both directions
    desc = run(api, uni, [], {"key": "pe_ratio", "dir": "desc"})
    assert desc["rows"][-1]["symbol"] == "SX:NIMBUS" and desc["matched"] == 6

    csv = api.post("/api/screener/export", json={"universe": uni, "filters": [], "sort": None})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.splitlines()
    assert lines[0].startswith("symbol,name,exchange,currency,country,sector,industry,last_price (currency)")
    assert any(line.startswith("SX:AURORA,Aurora Grid Power Ltd") for line in lines)
    assert "Universe: Watchlist · Screen me; 6 of 6 members matched." in lines[-1]


def test_saved_screens_and_custom_lists(api):
    lst = api.post("/api/screener/universes", json={"name": "My list", "symbols": "AURORA, SX:BANYAN\nBOGUS SX:SX50"})
    assert lst.status_code == 201, lst.text
    body = lst.json()
    assert body["symbols"] == ["SX:AURORA", "SX:BANYAN"]
    assert {s["symbol"] for s in body["skipped"]} == {"BOGUS", "SX:SX50"}
    assert api.post("/api/screener/universes", json={"name": "My list", "symbols": "AURORA"}).status_code == 409
    uni = {"kind": "list", "id": body["id"]}

    filters = [{"metric": "sector", "op": "in", "values": ["Utilities"]}]
    s = api.post("/api/screener/screens", json={"name": "Utilities", "universe": uni, "filters": filters})
    assert s.status_code == 201 and s.json()["filters"] == filters
    assert (
        api.post("/api/screener/screens", json={"name": "Utilities", "universe": uni, "filters": []}).status_code == 409
    )
    bad = api.post(
        "/api/screener/screens",
        json={"name": "Bad", "universe": uni, "filters": [{"metric": "pe_ratio", "op": "gte", "value": "x"}]},
    )
    assert bad.status_code == 422 and "plain number" in bad.json()["error"]["message"]
    assert api.delete(f"/api/screener/universes/{body['id']}").status_code == 409  # in use by "Utilities"

    sid = s.json()["id"]
    p = api.patch(f"/api/screener/screens/{sid}", json={"filters": [], "sort": {"key": "symbol", "dir": "desc"}})
    assert p.status_code == 200 and p.json()["filters"] == [] and p.json()["sort"]["dir"] == "desc"
    assert [x["name"] for x in api.get("/api/screener/screens").json()] == ["Utilities"]
    assert api.delete(f"/api/screener/screens/{sid}").status_code == 204
    assert api.delete(f"/api/screener/universes/{body['id']}").status_code == 204
    assert run_status(api, uni) == 404


def run_status(api, universe):
    return api.post("/api/screener/run", json={"universe": universe, "filters": []}).status_code


def test_heatmap_declares_universe_and_weighting(api):
    wid = watchlist(api, "Heat", ["SX:AURORA", "SX:GLASSWING", "SX:NIMBUS", "SX:HALCYON", "SX:ELARA"])
    uni = {"kind": "watchlist", "id": wid}
    cold = api.get(f"/api/screener/heatmap?kind=watchlist&id={wid}&metric=return_1m_pct").json()
    assert cold["dataset"]["loaded"] == 0 and all(s["value"] is None for s in cold["sectors"])
    refresh(api, uni)
    eq = api.get(f"/api/screener/heatmap?kind=watchlist&id={wid}&metric=return_1m_pct&weighting=equal").json()
    tech = next(s for s in eq["sectors"] if s["sector"] == "Technology")
    assert tech["members"] == 3 and tech["used"] == 3  # GLASSWING, NIMBUS, HALCYON
    vals = [Decimal(i["value"]) for i in tech["items"]]
    assert Decimal(tech["value"]) == (sum(vals) / 3).quantize(Decimal("0.01"))
    assert "equally weighted" in eq["method"]
    cw = api.get(f"/api/screener/heatmap?kind=watchlist&id={wid}&metric=return_1m_pct&weighting=market_cap").json()
    assert cw["weighting"] == "market_cap" and cw["fx"]["pair"] == "USD/INR"  # USD and INR members combined at a rate
    assert api.get(f"/api/screener/heatmap?kind=watchlist&id={wid}&metric=pe_ratio").status_code == 422


def test_peers_suggested_edited_and_reset(api):
    watchlist(api, "Tech", ["SX:GLASSWING", "SX:NIMBUS", "SX:HALCYON", "SX:ELARA"])
    refresh(api, {"kind": "watchlists"})
    g = api.get("/api/screener/peers/SX:GLASSWING").json()
    assert g["source"] == "suggested"
    assert [p["symbol"] for p in g["peers"]] == ["SX:NIMBUS", "SX:HALCYON"]  # same sector; same market first
    assert g["peers"][0]["reason"] == "Same sector (Technology)"
    assert [r["symbol"] for r in g["rows"]] == ["SX:GLASSWING", "SX:NIMBUS", "SX:HALCYON"]

    put = api.put("/api/screener/peers/SX:GLASSWING", json={"symbols": ["ELARA", "SX:HALCYON"]})
    assert put.status_code == 200, put.text
    assert put.json()["source"] == "saved" and [p["symbol"] for p in put.json()["peers"]] == ["SX:ELARA", "SX:HALCYON"]
    assert api.put("/api/screener/peers/SX:GLASSWING", json={"symbols": ["SX:GLASSWING"]}).status_code == 422
    assert api.put("/api/screener/peers/SX:GLASSWING", json={"symbols": ["SX:SX50"]}).status_code == 422
    six = ["SX:AURORA", "SX:BANYAN", "SX:COBALT", "SX:ELARA", "SX:FERRUM", "SX:HALCYON"]
    assert api.put("/api/screener/peers/SX:GLASSWING", json={"symbols": six}).status_code == 422
    reset = api.delete("/api/screener/peers/SX:GLASSWING").json()
    assert reset["source"] == "suggested"


def test_holdings_universe_and_worker_refresh(api, app):
    import asyncio

    from marketdesk.db import db_session
    from marketdesk.models import ScreenMetric
    from marketdesk.worker.__main__ import run_cycle

    assert (
        api.post(
            "/api/portfolio/transactions", json={"type": "DEPOSIT", "effective_date": "2026-01-05", "amount": "10000"}
        ).status_code
        == 201
    )
    buy = {"type": "BUY", "effective_date": "2026-01-06", "symbol": "SX:AURORA", "quantity": "5", "price": "150"}
    assert api.post("/api/portfolio/transactions", json=buy).status_code == 201
    opts = api.get("/api/screener/universes").json()["options"]
    assert next(o for o in opts if o["kind"] == "holdings")["count"] == 1
    summary = asyncio.run(run_cycle(app.state.market))
    assert summary["screener"]["refreshed"] == 1  # the worker keeps tracked snapshots current
    with db_session() as db:
        assert db.query(ScreenMetric).count() == 1
    res = run(api, {"kind": "holdings"})
    assert [r["symbol"] for r in res["rows"]] == ["SX:AURORA"] and res["dataset"]["loaded"] == 1


def test_backup_includes_screener_data_but_not_the_snapshot(api, tmp_path):
    wid = watchlist(api, "B", ["SX:AURORA"])
    refresh(api, {"kind": "watchlist", "id": wid})
    api.post("/api/screener/screens", json={"name": "S", "universe": {"kind": "watchlist", "id": wid}, "filters": []})
    api.put("/api/screener/peers/SX:AURORA", json={"symbols": ["SX:BANYAN"]})
    from marketdesk.services.backup import backup_tables

    names = {t.name for t in backup_tables()}
    assert {"screen_universes", "saved_screens", "peer_sets"} <= names and "screen_metrics" not in names

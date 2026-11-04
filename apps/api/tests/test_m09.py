"""M09: cash-flow-aware returns, splits never double counted, drawdowns, aligned correlations, exposure and
rebalance simulations — hand-checked vectors plus the API on the sample dataset."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal as D

from marketdesk.services import risk_math as rm
from marketdesk.services.ledger import LedgerEntry, TxnType

D1, D2, D3, D4 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)


def e(type_, day, seq, **kw):
    return LedgerEntry(ref=f"t{seq}", type=TxnType(type_), effective_date=day, seq=seq, **kw)


def lookup(**by_day):
    return rm.CloseLookup({date.fromisoformat(k): D(v) for k, v in by_day.items()})


def test_time_weighted_and_money_weighted_returns_hand_checked():
    # Day 1: deposit 1,000 and buy 10 @ 100. Day 2: close 110 (+10%). Day 3: deposit 1,100, close 110 (0%).
    # Day 4: close 99 → 990 + 1,100 cash = 2,090 (−5%). TWR = 1.10 × 1.00 × 0.95 − 1 = +4.5%.
    entries = [
        e("DEPOSIT", D1, 1, amount=D(1000)),
        e("BUY", D1, 2, symbol="X", quantity=D(10), price=D(100)),
        e("DEPOSIT", D3, 3, amount=D(1100)),
    ]
    prices = {"X": lookup(**{"2026-01-05": "100", "2026-01-06": "110", "2026-01-07": "110", "2026-01-08": "99"})}
    s = rm.value_series(entries, prices, [D1, D2, D3, D4])
    assert [(p.value, p.flow) for p in s.points] == [(D(1000), D(1000)), (D(1100), 0), (D(2200), D(1100)), (D(2090), 0)]
    index, rets = rm.twr_index(s.points)
    assert [round(r, 6) for _, r in rets] == [0.1, 0.0, -0.05]
    assert round(index[-1][1], 6) == 104.5
    # Money-weighted: 2,100 contributed, 2,090 at the end → a loss, although the time-weighted return is positive.
    mwr = rm.xirr(s.flows, D4, s.points[-1].value)
    assert mwr is not None and mwr < 0
    npv = sum(-float(a) / (1 + mwr) ** ((d - D1).days / 365) for d, a in s.flows) + 2090 / (1 + mwr) ** (3 / 365)
    assert abs(npv) < 1e-6
    assert rm.annualize(0.045, 3) is None  # never annualize a three-day return
    assert rm.xirr([], D4, D(0)) is None


def test_splits_are_counted_once_and_missing_closes_are_explicit():
    # The provider's closes are split-adjusted (2-for-1 on day 2): day-1 close 50 is really 100 as traded.
    closes = rm.as_traded([(D1, D(50)), (D2, D(51))], [(D2, D(2))])
    assert closes == {D1: D(100), D2: D(51)}
    entries = [
        e("DEPOSIT", D1, 1, amount=D(1000)),
        e("BUY", D1, 2, symbol="X", quantity=D(10), price=D(100)),
        e("SPLIT", D2, 3, symbol="X", split_from=D(1), split_to=D(2)),
    ]
    s = rm.value_series(entries, {"X": rm.CloseLookup(closes)}, [D1, D2])
    assert [p.value for p in s.points] == [D(1000), D(1020)]  # +2%, not −49% and not +104%
    # A close is carried forward for at most 10 days; beyond that the day is left out with the reason,
    # and its flows move to the next included day.
    late = D1 + timedelta(days=12)
    entries2 = [
        e("DEPOSIT", D1, 1, amount=D(1000)),
        e("BUY", D1, 2, symbol="X", quantity=D(1), price=D(100)),
        e("DEPOSIT", D3, 3, amount=D(50)),
    ]
    s2 = rm.value_series(
        entries2, {"X": lookup(**{"2026-01-05": "100", "2026-01-17": "120"})}, [D1, D3, D3 + timedelta(days=9), late]
    )
    assert [p.day for p in s2.points] == [D1, D3, late]
    assert s2.skipped[0][0] == D3 + timedelta(days=9) and "no close within 10 days for X" in s2.skipped[0][1]
    assert s2.points[1].flow == D(50) and s2.points[2].flow == 0


def test_drawdown_peak_trough_and_recovery():
    days = [D1 + timedelta(days=i) for i in range(5)]
    dd = rm.drawdowns(list(zip(days, [100.0, 120.0, 90.0, 110.0, 125.0], strict=True)))
    m = dd["max"]
    assert (
        round(m["depth"], 6) == -0.25 and m["peak"] == days[1] and m["trough"] == days[2] and m["recovered"] == days[4]
    )
    assert dd["current"] == 0.0
    open_dd = rm.drawdowns(list(zip(days[:4], [100.0, 120.0, 90.0, 110.0], strict=True)))
    assert open_dd["max"]["recovered"] is None and round(open_dd["current"], 4) == round(110 / 120 - 1, 4)


def test_volatility_needs_enough_observations():
    assert rm.volatility([0.01, -0.01] * 20) is None
    v = rm.volatility([0.01, -0.01] * 40)
    assert v is not None and abs(v - 0.01 * math.sqrt(80 / 79) * math.sqrt(252)) < 1e-12


def test_correlation_uses_aligned_dates_and_weekly_returns_across_markets():
    days = [
        date(2025, 1, 1) + timedelta(days=i) for i in range(400) if (date(2025, 1, 1) + timedelta(days=i)).weekday() < 5
    ]
    a = {d: D(100 + (i % 7)) for i, d in enumerate(days)}
    b = {d: D(200 + 2 * (i % 7)) for i, d in enumerate(days)}
    same = rm.correlation(a, b, same_market=True)
    assert same == {"r": 1.0, "n": len(days) - 1, "method": "daily", "why": None}
    # dates only one of them traded are not used (no carried-forward prices)
    b_holes = {d: v for i, (d, v) in enumerate(b.items()) if i % 10}
    assert rm.correlation(a, b_holes, True)["n"] == len(b_holes) - 1
    cross = rm.correlation(a, b, same_market=False)
    assert cross["method"] == "weekly" and cross["n"] >= 26
    short = rm.correlation(dict(list(a.items())[:20]), b, True)
    assert short["r"] is None and "at least 60" in short["why"]


def test_rebalance_simulation_vector():
    holdings = [rm.Holding("A", D(10), D(100)), rm.Holding("B", D(5), D(200)), rm.Holding("C", D(3), None)]
    out = rm.rebalance(holdings, D(0), {"A": D(50), "B": D(30), "Z": D(5)}, extra_cash=D(1000), fee_pct=D("0.1"))
    assert out["total"] == D(3000)  # 1,000 + 1,000 + 1,000 extra; C has no price and is left out
    a, b = out["rows"]
    assert (a["trade_shares"], a["trade_value"], a["fee"]) == (D(5), D(500), D("0.5"))
    assert b["trade_shares"] == 0 and b["trade_value"] == 0  # −0.5 shares rounds toward zero
    assert out["cash_after"] == D("499.5") and round(a["new_weight_pct"], 4) == 50
    assert out["unpriced"] == ["C"] and out["targets_without_holding"] == ["Z"]
    frac = rm.rebalance(holdings[:2], D(0), {"A": D(50), "B": D(30)}, extra_cash=D(1000), whole_shares=False)
    assert frac["rows"][1]["trade_shares"] == D("-0.5") and frac["cash_after"] == D(600)
    over = rm.rebalance(holdings[:2], D(0), {"A": D(100)}, whole_shares=False)
    assert over["warnings"] == [] and over["cash_after"] == D(0)
    neg = rm.rebalance(holdings[:2], D(0), {"A": D(100), "B": D(50)}, whole_shares=False)
    assert neg["warnings"] and neg["cash_after"] < 0


# -------------------------------------------------------------------------------------------- API on sample data
def post(api, **body):
    r = api.post("/api/portfolio/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_performance_api_consistent_with_the_ledger(api):
    assert api.get("/api/portfolio/performance").json()["available"] is False
    post(api, type="DEPOSIT", effective_date="2025-01-02", amount="200000")
    post(api, type="BUY", effective_date="2025-01-03", symbol="SX:AURORA", quantity="300", price="150")
    post(api, type="BUY", effective_date="2025-02-03", symbol="SX:ELARA", quantity="40", price="800")
    post(api, type="DEPOSIT", effective_date="2025-06-02", amount="20000")
    post(api, type="DIVIDEND", effective_date="2025-06-12", symbol="SX:AURORA", amount="1200")
    r = api.get("/api/portfolio/performance", params={"account": "INR"}).json()
    assert r["available"] is True and r["currency"] == "INR" and r["start"] == "2025-01-02"
    m = r["metrics"]
    summary = api.get("/api/portfolio/summary", params={"currency": "INR"}).json()
    assert D(m["end_value"]) == D(summary["total_equity"])  # the last valued day agrees with the holdings view
    assert m["flows_count"] == 2 and D(m["net_flows"]) == D(220000)
    assert m["twr_annualized_pct"] is not None and m["mwr_annualized_pct"] is not None  # > 1 year
    assert m["volatility_pct"] is not None and r["observations"] >= 60
    assert D(m["max_drawdown"]["depth_pct"]) <= 0
    s = r["series"]
    assert len(s["dates"]) == len(s["index"]) == len(s["benchmark"]) == len(s["underwater"]) == len(s["value"])
    assert s["index"][0] == 100.0 and s["benchmark"][0] == 100.0
    b = r["benchmark"]
    assert b["symbol"] == "SX:SX50" and b["total_pct"] is not None and b["beta"] is not None and b["n"] >= 60
    assert r["warnings"] == [] and any("split" in p for p in r["policies"])
    # ELARA's 2-for-1 split (2024-03-15) is before the purchase: nothing to record, no warning.
    other = api.get("/api/portfolio/performance", params={"benchmark": "SX:SXFIN"}).json()
    assert other["benchmark"]["symbol"] == "SX:SXFIN"


def test_unrecorded_split_is_flagged(api):
    post(api, type="DEPOSIT", effective_date="2024-01-02", amount="100000")
    post(api, type="BUY", effective_date="2024-01-03", symbol="SX:ELARA", quantity="20", price="1500")
    r = api.get("/api/portfolio/performance").json()
    assert any("SX:ELARA" in w and "2024-03-15" in w for w in r["warnings"])


def test_exposure_correlations_targets_and_rebalance(api):
    post(api, type="DEPOSIT", effective_date="2025-01-02", amount="100000")
    post(api, type="BUY", effective_date="2025-01-03", symbol="SX:AURORA", quantity="200", price="150")
    post(api, type="BUY", effective_date="2025-01-03", symbol="SX:GLASSWING", quantity="20", price="1500")
    x = api.get("/api/portfolio/exposure").json()
    assert x["available"] and x["currency"] == "INR"
    assert {r["name"] for r in x["by_sector"]} == {"Utilities", "Technology"}
    assert abs(sum(D(r["pct_of_invested"]) for r in x["by_holding"]) - 100) < D("0.02")
    assert x["by_country"][0]["name"] in ("IN", "Unknown") and x["concentration"]["effective_holdings"] is not None
    c = api.get("/api/portfolio/correlations").json()
    assert c["symbols"][-1] == "SX:SX50" and c["benchmark"] == "SX:SX50"
    cell = c["matrix"][0][1]
    assert cell["method"] == "daily" and cell["n"] >= 60 and -1 <= float(cell["r"]) <= 1

    bad = api.put(
        "/api/portfolio/targets",
        params={"account": "INR"},
        json={"targets": [{"symbol": "SX:AURORA", "target_pct": "70"}, {"symbol": "SX:GLASSWING", "target_pct": "40"}]},
    )
    assert bad.status_code == 422 and "more than 100%" in bad.json()["error"]["message"]
    dup = api.put("/api/portfolio/targets", json={"targets": [{"symbol": "SX:AURORA", "target_pct": "10"}] * 2})
    assert dup.status_code == 422
    ok = api.put(
        "/api/portfolio/targets",
        json={"targets": [{"symbol": "sx:aurora", "target_pct": "40"}, {"symbol": "SX:GLASSWING", "target_pct": "40"}]},
    )
    assert ok.status_code == 200 and ok.json()["targets"] == [
        {"symbol": "SX:AURORA", "target_pct": "40.00"},
        {"symbol": "SX:GLASSWING", "target_pct": "40.00"},
    ]
    sim = api.post("/api/portfolio/rebalance", json={"account": "INR", "extra_cash": "10000"}).json()
    assert {r["symbol"] for r in sim["rows"]} == {"SX:AURORA", "SX:GLASSWING"}
    assert "no orders are placed" in sim["note"] and sim["marks_complete"] is True
    total = D(sim["total"])
    for row in sim["rows"]:
        assert abs(D(row["new_value"]) - total * D("0.4")) <= D(row["price"])  # within one share of target
    # the simulation changed nothing
    assert len(api.get("/api/portfolio/transactions").json()["items"]) == 3


def test_consolidated_performance_converts_usd_daily(api):
    post(api, type="DEPOSIT", effective_date="2025-06-02", amount="200000")
    post(
        api,
        type="FX",
        effective_date="2025-06-03",
        currency="INR",
        counter_currency="USD",
        amount="84000",
        counter_amount="1000",
        fees="50",
        fx_rate="84",
        fx_source="Sample bank",
        fx_time="2025-06-03T10:30:00+05:30",
    )
    post(api, type="BUY", effective_date="2025-06-04", symbol="SX:HALCYON", quantity="5", price="150", currency="USD")
    post(api, type="BUY", effective_date="2025-06-04", symbol="SX:AURORA", quantity="200", price="150")
    usd = api.get("/api/portfolio/performance", params={"account": "USD"}).json()
    assert usd["available"] and usd["currency"] == "USD" and usd["metrics"]["flows_count"] == 1  # the FX transfer in
    allv = api.get("/api/portfolio/performance", params={"account": "ALL"}).json()
    assert allv["available"] and allv["currency"] == "INR"
    assert allv["metrics"]["flows_count"] == 1  # only the external INR deposit; the conversion is internal
    assert any("USD/INR close" in n for n in allv["notes"])
    assert allv["benchmark"]["beta"] is None and "every holding trades" in allv["benchmark"]["beta_note"]
    ex = api.get("/api/portfolio/exposure", params={"account": "ALL"}).json()
    assert {r["name"] for r in ex["by_currency"]} == {"INR", "USD"} and "USD/INR" in ex["rates"]

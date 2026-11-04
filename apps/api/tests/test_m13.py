"""M13: rule tests trade at the next open (never the signal's close), costs and dividends handled, runs reproducible,
paper portfolio isolated with next-open fills."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from marketdesk.services import sim_math as sm

D0 = date(2026, 1, 5)


def days(n):
    return [D0 + timedelta(days=i) for i in range(n)]


def test_signals_use_only_past_closes():
    closes = [D(100 + (i % 9) * 3 - i // 5) for i in range(120)]
    full = sm.signals("sma_cross", closes, {"fast": 5, "slow": 20})
    for k in (25, 60, 119):
        assert sm.signals("sma_cross", closes[: k + 1], {"fast": 5, "slow": 20}) == full[: k + 1]
    mom = sm.signals("momentum", closes, {"lookback": 10})
    assert mom[:10] == [False] * 10 and mom[10] == (closes[10] > closes[0])
    with pytest.raises(ValueError):
        sm.validate_params("sma_cross", {"fast": 50, "slow": 20})


def test_execution_at_next_open_with_costs_hand_vector():
    d = days(3)
    bars = [sm.Bar(d[0], D(10), D(10)), sm.Bar(d[1], D(20), D(20)), sm.Bar(d[2], D(25), D(30))]
    free = sm.run_rule(bars, "buy_and_hold", {}, sm.Costs(), D(1000))
    t = free["trades"][0]
    assert (t["day"], t["signal_day"], t["price"], t["qty"]) == (d[1].isoformat(), d[0].isoformat(), D(20), D(50))
    assert free["equity"][-1][1] == D(1500)  # 50 × 30
    costly = sm.run_rule(bars, "buy_and_hold", {}, sm.Costs(D(1), D(100)), D(1000))
    t = costly["trades"][0]
    # 1000 ÷ (20.2 × 1.01) = 49.01 → 49 shares; value 989.8, fee 9.898, cash left 0.302
    assert t["price"] == D("20.2") and t["qty"] == D(49) and t["fee"] == D("9.898")
    assert costly["equity"][-1][1] == D("1470.302")  # 0.302 + 49 × 30


def test_dividends_on_the_adjusted_basis_and_data_hash():
    d = days(4)
    adj = sm.adjusted_dividends([(d[2], D(2))], [(d[3], D(2))])  # a 2-for-1 split after the ex-date
    assert adj == {d[2]: D(1)}
    bars = [sm.Bar(x, D(10), D(10)) for x in d]
    r = sm.run_rule(bars, "buy_and_hold", {}, sm.Costs(), D(100), adj)
    assert r["final_shares"] == D(10) and r["final_cash"] == D(10)  # 10 shares × 1 dividend credited
    h1 = sm.data_hash(bars, adj)
    assert h1 == sm.data_hash(list(bars), dict(adj)) and h1 != sm.data_hash(bars[:-1], adj)


def test_summary_drawdown():
    d = days(400)
    eq = [(d[i], D(100) + (D(20) if 100 <= i < 200 else 0) - (D(30) if 200 <= i < 250 else 0)) for i in range(400)]
    s = sm.summarize(eq, D(100))
    assert round(s["max_drawdown_pct"], 4) == round((70 / 120 - 1) * 100, 4) and s["cagr_pct"] is not None


def test_paper_fills():
    d = days(3)
    bars = {"X": [sm.Bar(d[0], D(10), D(10)), sm.Bar(d[1], D(11), D(12))]}
    orders = [
        sm.Order(1, "BUY", "X", D(5), d[0]),
        sm.Order(2, "BUY", "X", D(500), d[0]),  # too expensive after order 1
        sm.Order(3, "SELL", "X", D(9), d[0]),  # more than held
        sm.Order(4, "BUY", "X", D(1), d[1]),  # no session after d[1] yet
    ]
    st = sm.fill_orders(orders, bars, sm.Costs(), D(100))
    assert st["orders"][1]["status"] == "filled" and st["orders"][1]["fill_price"] == D(11)
    assert st["orders"][2]["status"] == "rejected" and "cash" in st["orders"][2]["reason"]
    assert st["orders"][3]["status"] == "rejected" and st["orders"][4]["status"] == "pending"
    assert st["cash"] == D(45) and st["positions"] == {"X": D(5)}


# -------------------------------------------------------------------------------------------- API on sample data
def test_rule_test_run_is_recorded_and_reproducible(api):
    bad = api.post(
        "/api/lab/runs", json={"symbol": "SX:AURORA", "rule": "sma_cross", "params": {"fast": 60, "slow": 20}}
    )
    assert bad.status_code == 422
    r = api.post(
        "/api/lab/runs",
        json={
            "symbol": "SX:AURORA",
            "rule": "sma_cross",
            "params": {"fast": 20, "slow": 50},
            "fee_pct": "0.1",
            "slippage_bps": "10",
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["data"]["provider"] == "fixture" and len(run["data"]["hash"]) == 64 and run["data"]["bars"] > 1000
    s = run["results"]["strategy"]
    assert s["trades"] > 0 and s["end_value"] is not None and "Simulated" in run["label"]
    assert all(t["signal_day"] < t["day"] for t in run["results"]["trades"])  # signal strictly before execution
    assert run["results"]["equity"][-1][1] == s["end_value"]  # the chart ends on the table's value
    assert run["results"]["hold_equity"][-1][1] == run["results"]["buy_and_hold"]["end_value"]
    assert run["results"]["benchmark"]["symbol"] == "SX:SX50"
    rep = api.post(f"/api/lab/runs/{run['id']}/reproduce").json()
    assert rep["same_data"] is True and rep["same_results"] is True
    assert [x["id"] for x in api.get("/api/lab/runs").json()] == [run["id"]]
    assert {i["title"] for i in api.get("/api/lab/review").json()["items"]} >= {
        "Survivorship bias",
        "Signals precede execution",
    }


def test_paper_portfolio_is_isolated_and_fills_at_next_open(api):
    pf = api.post(
        "/api/lab/paper", json={"name": "Trial", "starting_cash": "100000", "fee_pct": "0", "slippage_bps": "0"}
    ).json()
    st = api.post(
        f"/api/lab/paper/{pf['id']}/orders", json={"side": "BUY", "symbol": "SX:AURORA", "quantity": "10"}
    ).json()
    o = st["orders"][0]
    assert o["status"] == "pending" and o["placed_session"] == "2026-06-30"
    assert (
        api.post(
            f"/api/lab/paper/{pf['id']}/orders", json={"side": "BUY", "symbol": "SX:HALCYON", "quantity": "1"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            f"/api/lab/paper/{pf['id']}/orders", json={"side": "BUY", "symbol": "SX:AURORA", "quantity": "1.5"}
        ).status_code
        == 422
    )
    api.post("/api/fixture/advance")  # the next sample session becomes available
    st = api.get(f"/api/lab/paper/{pf['id']}").json()
    o = st["orders"][0]
    assert o["status"] == "filled" and o["fill_day"] == "2026-07-01"
    assert D(st["cash"]) == D(100000) - D(10) * D(o["fill_price"])
    assert st["positions"][0]["symbol"] == "SX:AURORA" and D(st["positions"][0]["quantity"]) == 10
    late = api.post(
        f"/api/lab/paper/{pf['id']}/orders", json={"side": "SELL", "symbol": "SX:AURORA", "quantity": "4"}
    ).json()
    pend = [x for x in late["orders"] if x["status"] == "pending"]
    assert len(pend) == 1
    left = api.delete(f"/api/lab/paper/{pf['id']}/orders/{pend[0]['id']}").json()
    assert all(x["status"] != "pending" for x in left["orders"])
    assert api.delete(f"/api/lab/paper/{pf['id']}/orders/{o['id']}").status_code == 409  # filled: not cancellable
    assert api.get("/api/portfolio/transactions").json()["items"] == []  # the real ledger is untouched


def test_lab_data_in_backups():
    from marketdesk.services.backup import backup_tables

    assert {"research_runs", "paper_portfolios", "paper_orders"} <= {t.name for t in backup_tables()}

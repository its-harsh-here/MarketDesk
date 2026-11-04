"""M11: deterministic DCF with rejected invalid assumptions, sensitivity grids, peer-multiple ranges, saved scenarios,
portfolio stress tests — hand-checked vectors plus the API on the sample dataset."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from marketdesk.services import valuation_math as vm


def inp(**over):
    base = dict(fcf0=D(100), years=2, growth_pct=D(10), terminal_growth_pct=D(2), discount_pct=D(10), shares=D(10))
    base.update(over)
    return vm.DcfInputs(**base)


def test_dcf_hand_vector():
    # FCF1 = 110 → PV 100; FCF2 = 121 → PV 100; TV = 121 × 1.02 ÷ 0.08 = 1,542.75 → PV 1,275; equity 1,475.
    out = vm.dcf(inp())
    assert [r["fcf"] for r in out["rows"]] == [D("110.0"), D("121.00")]
    assert [round(r["pv"], 10) for r in out["rows"]] == [D(100), D(100)]
    assert out["terminal_value"] == D("1542.75")
    assert round(out["pv_terminal"], 10) == D(1275)
    assert round(out["equity_value"], 10) == D(1475) and round(out["per_share"], 10) == D("147.5")
    assert round(out["terminal_share_pct"], 2) == D("86.44")


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"discount_pct": D(3), "terminal_growth_pct": D(3)}, "terminal_growth_pct"),  # r = g_T: infinite
        ({"discount_pct": D(3), "terminal_growth_pct": D("2.6")}, "terminal_growth_pct"),  # within 0.5 pp
        ({"fcf0": D(-5)}, "fcf0"),
        ({"years": 0}, "years"),
        ({"years": 16}, "years"),
        ({"discount_pct": D(45)}, "discount_pct"),
        ({"terminal_growth_pct": D(11)}, "terminal_growth_pct"),
        ({"growth_pct": D(-60)}, "growth_pct"),
        ({"shares": D(0)}, "shares"),
    ],
)
def test_invalid_assumptions_are_rejected(over, field):
    with pytest.raises(vm.ValuationError) as err:
        inp(**over).validate()
    assert err.value.field == field


def test_parse_rejects_non_numbers():
    with pytest.raises(vm.ValuationError, match="plain number"):
        vm.DcfInputs.parse(
            {"fcf0": "lots", "years": 5, "growth_pct": 5, "terminal_growth_pct": 3, "discount_pct": 10, "shares": 1}
        )
    ok = vm.DcfInputs.parse(
        {
            "fcf0": "1,000",
            "years": "5",
            "growth_pct": "5",
            "terminal_growth_pct": "3",
            "discount_pct": "10",
            "shares": "10",
        }
    )
    assert ok.fcf0 == D(1000) and ok.years == 5


def test_sensitivity_grid_centre_and_invalid_cells():
    base = inp(discount_pct=D(6), terminal_growth_pct=D(4))
    s = vm.sensitivity(base, "discount_pct", "terminal_growth_pct")
    assert s["rows"] == [D(4), D(5), D(6), D(7), D(8)] and s["cols"] == [D(3), D("3.5"), D(4), D("4.5"), D(5)]
    assert s["grid"][2][2]["value"] == vm.dcf(base)["per_share"]
    assert s["grid"][0][2]["value"] is None and "0.5 percentage points" in s["grid"][0][2]["why"]  # r 4%, g_T 4%
    vals = [row[2]["value"] for row in s["grid"][1:]]
    assert all(a > b for a, b in zip(vals, vals[1:], strict=False))  # higher discount rate → lower value
    with pytest.raises(vm.ValuationError):
        vm.sensitivity(base, "discount_pct", "discount_pct")


def test_multiple_ranges():
    r = vm.multiple_range([D(10), D(20), D(30), D(-4)], D(5))  # negative multiples are not comparable
    assert r["n"] == 3 and r["implied"] == {"min": D(50), "p25": D(75), "median": D(100), "p75": D(125), "max": D(150)}
    assert vm.multiple_range([D(10), D(20)], None)["available"] is False
    assert "at least 2" in vm.multiple_range([D(10)], D(5))["why"]


def test_stress_vector():
    holdings = [
        vm.StressHolding("A.NS", "INR", "IN", D(1000)),
        vm.StressHolding("B", "USD", "US", D(100)),
        vm.StressHolding("C.NS", "INR", "IN", D(200)),
    ]
    out = vm.stress(
        holdings,
        {"INR": D(500), "USD": D(10)},
        {"INR": D(1), "USD": D(80)},
        "INR",
        {"IN": D(-10), "US": D(-20)},
        {"C.NS": D(-50)},
        {"USD": D(5)},
    )
    # before: 1,000 + 8,000 + 200 + 500 + 800 = 10,500
    # after: 900 + 100 × 0.8 × 80 × 1.05 = 6,720 + 100 (C −50%) + 500 + 840 = 9,060
    assert out["before"] == D(10500) and out["after"] == D(9060) and out["change"] == D(-1440)
    assert {r["symbol"]: r["price_shock_pct"] for r in out["rows"]}["C.NS"] == D(-50)
    with pytest.raises(vm.ValuationError):
        vm.stress(holdings, {}, {"INR": D(1), "USD": D(80)}, "INR", {"IN": D(-150)}, {}, {})


def test_statement_cache_entries_from_before_m11_still_load():
    from marketdesk.providers.serialize import statements_from

    st = statements_from(
        {
            "instrument": {
                "symbol": "X",
                "name": None,
                "exchange": None,
                "currency": None,
                "timezone": None,
                "kind": None,
            },
            "periods": [["2025-03-31", "10", "1", None, "5"]],
            "source": "s",
            "notes": [],
        }
    )
    assert st.periods[0].operating_cash_flow is None and st.periods[0].total_equity == D(5)


# -------------------------------------------------------------------------------------------- API on sample data
def test_inputs_defaults_and_applicability(api):
    a = api.get("/api/valuation/SX:AURORA/inputs").json()
    assert a["dcf_applicable"] is True and a["currency"] == "INR"
    d = a["defaults"]
    assert d["fcf0"]["value"] == "18886000000" and "operating cash flow − capital expenditure" in d["fcf0"]["source"]
    assert d["shares"]["value"] == "1900000000" and d["shares"]["source"].startswith("Implied")
    assert 0 <= float(d["growth_pct"]["value"]) <= 15 and d["discount_pct"]["source"].startswith("Assumption")
    bank = api.get("/api/valuation/SX:PEREGRINE/inputs").json()
    assert bank["dcf_applicable"] is False and "banks" in bank["dcf_reason"]
    payload = {k: v["value"] for k, v in d.items()}
    refused = api.post("/api/valuation/SX:PEREGRINE/dcf", json={"inputs": payload})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "dcf_not_applicable"
    loss = api.get("/api/valuation/SX:NIMBUS/inputs").json()
    assert "not positive" in loss["defaults"]["fcf0"]["warning"]
    bad = api.post(
        "/api/valuation/SX:NIMBUS/dcf", json={"inputs": {**payload, "fcf0": loss["defaults"]["fcf0"]["value"]}}
    )
    assert bad.status_code == 422 and bad.json()["error"]["details"]["field"] == "fcf0"


def test_dcf_run_with_sensitivity(api):
    d = api.get("/api/valuation/SX:AURORA/inputs").json()["defaults"]
    payload = {k: v["value"] for k, v in d.items()}
    r = api.post(
        "/api/valuation/SX:AURORA/dcf", json={"inputs": payload, "rows_axis": "discount_pct", "cols_axis": "growth_pct"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["per_share"] is not None and body["result"]["vs_price_pct"] is not None
    assert len(body["sensitivity"]["grid"]) == 5 and len(body["sensitivity"]["grid"][0]) == 5
    assert body["sensitivity"]["grid"][2][2]["value"] == body["result"]["per_share"]
    assert "Hypothetical" in body["hypothetical"] and "Gordon" in body["formula"]
    inv = api.post(
        "/api/valuation/SX:AURORA/dcf", json={"inputs": {**payload, "discount_pct": "4", "terminal_growth_pct": "4"}}
    )
    assert inv.status_code == 422 and inv.json()["error"]["details"]["field"] == "terminal_growth_pct"


def test_multiples_use_the_peer_group(api):
    wl = api.post("/api/watchlists", json={"name": "Peers"}).json()["id"]
    for s in ("SX:GLASSWING", "SX:NIMBUS", "SX:HALCYON", "SX:ELARA", "SX:COBALT"):
        api.post(f"/api/watchlists/{wl}/items", json={"symbol": s})
    m = api.get("/api/valuation/SX:GLASSWING/multiples").json()
    assert m["peer_source"] == "suggested peers"
    assert m["ranges"]["pe_ratio"]["available"] is False  # NIMBUS has no P/E: only one peer with a positive multiple
    api.put("/api/screener/peers/SX:GLASSWING", json={"symbols": ["SX:HALCYON", "SX:ELARA", "SX:COBALT"]})
    m = api.get("/api/valuation/SX:GLASSWING/multiples").json()
    pe = m["ranges"]["pe_ratio"]
    assert m["peer_source"] == "your peer group" and pe["available"] is True and pe["n"] == 3
    eps = D(m["price"]) / D(m["own"]["pe_ratio"])
    assert abs(D(pe["implied"]["median"]) - D(pe["multiples"]["median"]) * eps) < D("0.01")


def test_scenarios_crud(api):
    d = api.get("/api/valuation/SX:AURORA/inputs").json()["defaults"]
    payload = {k: v["value"] for k, v in d.items()}
    ids = []
    for case, g in (("bear", "0"), ("base", "6"), ("bull", "12")):
        r = api.post(
            "/api/valuation/SX:AURORA/scenarios",
            json={"name": case.title(), "case": case, "inputs": {**payload, "growth_pct": g}, "notes": f"{case} case"},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    assert api.post("/api/valuation/SX:AURORA/scenarios", json={"name": "Bear", "inputs": payload}).status_code == 409
    bad = api.post(
        "/api/valuation/SX:AURORA/scenarios", json={"name": "Silly", "inputs": {**payload, "discount_pct": "2"}}
    )
    assert bad.status_code == 422
    rows = api.get("/api/valuation/SX:AURORA/scenarios").json()
    assert [(s["case"], s["inputs"]["growth_pct"]) for s in rows] == [("bear", "0"), ("base", "6"), ("bull", "12")]
    up = api.put(
        f"/api/valuation/scenarios/{ids[0]}",
        json={"name": "Bear", "case": "bear", "inputs": {**payload, "growth_pct": "-2"}, "notes": "worse"},
    )
    assert up.status_code == 200 and up.json()["inputs"]["growth_pct"] == "-2" and up.json()["notes"] == "worse"
    assert api.delete(f"/api/valuation/scenarios/{ids[2]}").status_code == 204
    assert len(api.get("/api/valuation/SX:AURORA/scenarios").json()) == 2


def test_portfolio_stress_matches_the_overview(api):
    def post(**b):
        r = api.post("/api/portfolio/transactions", json=b)
        assert r.status_code == 201, r.text

    post(type="DEPOSIT", effective_date="2026-01-02", amount="200000")
    post(
        type="FX",
        effective_date="2026-01-05",
        currency="INR",
        counter_currency="USD",
        amount="84000",
        counter_amount="1000",
        fees="50",
        fx_rate="84",
        fx_source="Sample bank",
        fx_time="2026-01-05T10:30:00+05:30",
    )
    post(type="BUY", effective_date="2026-01-06", symbol="SX:HALCYON", quantity="5", price="150", currency="USD")
    post(type="BUY", effective_date="2026-01-06", symbol="SX:AURORA", quantity="200", price="150")
    ov = api.get("/api/portfolio/overview").json()
    s = api.post(
        "/api/portfolio/stress",
        json={"account": "ALL", "market_shocks": {"IN": "-10", "US": "-20"}, "fx_shocks": {"USD": "5"}},
    ).json()
    assert s["available"] and abs(D(s["before"]) - D(ov["total_in_base"])) < D("0.01")
    assert D(s["change"]) < 0 and {r["market"] for r in s["rows"]} == {"IN", "US"}
    assert "not a forecast" in s["method"]
    none = api.post("/api/portfolio/stress", json={"account": "ALL"}).json()
    assert D(none["change"]) == 0
    bad = api.post("/api/portfolio/stress", json={"account": "ALL", "market_shocks": {"IN": "-150"}})
    assert bad.status_code == 422


def test_scenarios_are_backed_up():
    from marketdesk.services.backup import backup_tables

    assert "valuation_scenarios" in {t.name for t in backup_tables()}

"""Terminal T2: financial analysis — hand-checked vectors for per-share, common-size, margins, growth, CAGR,
returns (ROIC with stated tax rule), and point-in-time valuation bands across a stock split."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from marketdesk.services import fin_analysis as fa

ENDS = [date(2025, 12, 31), date(2024, 12, 31), date(2023, 12, 31), date(2022, 12, 31)]
FILED = {ENDS[0]: date(2026, 2, 1), ENDS[1]: date(2025, 2, 1), ENDS[2]: date(2024, 2, 1), ENDS[3]: date(2023, 2, 1)}

DATA = {  # key: (unit, kind, {end index: value})
    "revenue": ("USD", "d", {0: 1000, 1: 800, 2: 640, 3: 512}),
    "cost_of_revenue": ("USD", "d", {0: 600, 1: 480}),
    "gross_profit": ("USD", "d", {0: 400, 1: 320}),
    "operating_income": ("USD", "d", {0: 200, 1: 160}),
    "pretax_income": ("USD", "d", {0: 180, 1: 150}),
    "income_tax": ("USD", "d", {0: 36, 1: 90}),  # 2024: 60% → outside 0–50%
    "net_income": ("USD", "d", {0: 144, 1: 100, 2: 80, 3: -10}),
    "eps_diluted": ("USD/shares", "d", {0: "1.44", 1: "1.0"}),
    "shares_diluted": ("shares", "d", {0: 100, 1: 100}),
    "cash": ("USD", "i", {0: 100, 1: 80}),
    "total_assets": ("USD", "i", {0: 2000, 1: 1800}),
    "total_liabilities": ("USD", "i", {0: 1000}),
    "equity": ("USD", "i", {0: 1000, 1: 900}),
    "long_term_debt": ("USD", "i", {0: 300, 1: 300}),
    "current_debt": ("USD", "i", {0: 50, 1: 50}),
    "operating_cash_flow": ("USD", "d", {0: 250, 1: 200}),
    "capex": ("USD", "d", {0: 50, 1: 40}),
    "depreciation": ("USD", "d", {0: 30, 1: 20}),
}


def statements(period="annual"):
    lines = []
    for key, (unit, kind, vals) in DATA.items():
        values = [
            {
                "value": D(str(v)),
                "unit": unit,
                "end": ENDS[i],
                "start": date(ENDS[i].year, 1, 1) if kind == "d" else None,
                "form": "10-K",
                "filed": FILED[ENDS[i]],
                "accession": f"a{i}",
                "prior": [],
            }  # fmt: skip
            for i, v in vals.items()
        ]
        lines.append({"key": key, "values": values})
    return {"period": period, "period_ends": ENDS, "currency": "USD", "lines": lines}


def row(table, key):
    return next(r for r in table["rows"] if r["key"] == key)


def test_per_share_common_size_and_margins():
    st = statements()
    ps = fa.per_share(st)
    assert row(ps, "revenue_ps")["values"][0] == 10 and row(ps, "fcf_ps")["values"][0] == 2
    assert row(ps, "book_ps")["values"][0] == 10 and row(ps, "eps")["values"][0] == D("1.44")
    assert row(ps, "revenue_ps")["values"][2] is None and "share count" in row(ps, "revenue_ps")["why"][2]
    cs = fa.common_size(st)
    assert row(cs, "cs_cost_of_revenue")["values"][0] == 60 and row(cs, "cs_cash")["values"][0] == 5
    m = fa.margins(st)
    keys = ("gross_margin", "operating_margin", "ebitda_margin", "net_margin", "fcf_margin")
    assert [row(m, k)["values"][0] for k in keys] == [40, 20, 23, D("14.4"), 20]


def test_growth_and_cagr():
    st = statements()
    g = fa.growth(st)
    assert row(g, "g_revenue")["values"][0] == 25
    ni = row(g, "g_net_income")
    assert ni["values"][2] is None and "zero or negative" in ni["why"][2]  # 2023 vs a loss in 2022
    c = fa.cagr(st)
    rev = row(c, "cagr_revenue")
    assert abs(float(rev["values"][0]) - 25.0) < 1e-9 and rev["values"][1] is None and "Fewer than 5" in rev["why"][1]
    assert row(c, "cagr_net_income")["values"][0] is None  # started from a loss
    assert fa.cagr(statements("quarterly"))["rows"] == []


def test_returns_and_roic_rules():
    r = fa.returns(statements())
    assert row(r, "roe")["values"][0] == D("14.4")
    assert row(r, "roic")["values"][0] == D("12.8")  # 200 × 0.8 ÷ (1000 + 300 + 50 − 100)
    assert row(r, "tax_rate")["values"][0] == 20
    roic24 = row(r, "roic")
    assert roic24["values"][1] is None and "tax rate" in roic24["why"][1]  # 60% is outside 0–50%
    assert roic24["values"][2] is None  # 2023: inputs missing, explained
    assert abs(float(row(r, "cash_conversion")["values"][0]) - 250 / 144 * 100) < 1e-9
    assert fa.returns(statements("quarterly"))["rows"] == []


def test_valuation_bands_are_point_in_time_and_split_aware():
    st = statements()
    split = [(date(2025, 6, 1), D(2))]  # 2-for-1 after FY2024 was filed, before FY2025
    bars = [(date(2025, 1, 15), D(9)), (date(2025, 3, 1), D(10)), (date(2026, 3, 1), D("14.4"))]
    b = fa.valuation_bands(st, bars, split, "USD")
    # 15 Jan 2025: FY2023 EPS is not in the data → no P/E; 1 Mar 2025: FY2024 EPS 1.00 → 0.50 on today's basis → 20
    # 1 Mar 2026: FY2025 EPS 1.44 (filed after the split) → 10
    assert b["pe"]["n"] == 2 and b["pe"]["max"] == 20 and b["pe"]["min"] == 10 and b["pe"]["current"] == 10
    assert b["pe"]["percentile"] == 50
    # EV/EBITDA on 1 Mar 2026: (14.4 × 100 + 350 − 100) ÷ 230; on 1 Mar 2025: (10 × 200 + 350 − 80) ÷ 180
    assert abs(b["ev_ebitda"]["current"] - 1690 / 230) < 1e-9 and abs(b["ev_ebitda"]["max"] - 2270 / 180) < 1e-9
    assert fa.valuation_bands(st, bars, split, "INR")["pe"] is None  # never mix currencies


def test_provider_statements_run_the_same_analysis(api):
    r = api.get("/api/terminal/financial-analysis", params={"symbol": "SX:AURORA"}).json()
    assert r["official"] is False and "unofficial" in r["source"] and r["period"] == "annual"
    g = {x["key"]: x for x in r["growth"]["rows"]}
    assert "g_revenue" in g and any(v is not None for v in g["g_revenue"]["values"])
    assert r["bands"]["pe"] is None and "EPS" in r["bands"]["reason"]
    assert all(isinstance(v, (str, type(None))) for v in g["g_revenue"]["values"])  # decimals as strings
    q = api.get("/api/terminal/financial-analysis", params={"symbol": "SX:AURORA", "period": "quarterly"}).json()
    assert q["period"] == "annual" and any("annual provider statements only" in n for n in q["notes"])

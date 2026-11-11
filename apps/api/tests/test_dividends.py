"""Dividend summary: TTM total and yield, frequency, calendar-year totals, 5-year growth on complete years,
increase streak, no-dividend case, API on sample data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from marketdesk.services import dividends as dv


def test_summary_hand_vector():
    # quarterly payer: 0.20 a quarter in 2019, +0.01 each year after; 2026 has two payments so far
    divs = []
    for y in range(2019, 2026):
        for m in (2, 5, 8, 11):
            divs.append((date(y, m, 10), D("0.20") + D("0.01") * (y - 2019)))
    divs += [(date(2026, 2, 10), D("0.27")), (date(2026, 5, 10), D("0.27"))]
    s = dv.summary(divs, date(2026, 6, 30), D("100"))
    # TTM: Aug and Nov 2025 (0.26 each) + Feb and May 2026 (0.27 each) = 1.06
    assert s["ttm"]["total"] == D("1.06") and s["ttm"]["payments"] == 4 and s["ttm"]["yield_pct"] == D("1.06")
    assert s["frequency"] == "quarterly" and s["last"] == {"ex_date": "2026-05-10", "amount": D("0.27")}
    assert s["indicated"] == {"total": D("1.08"), "per_year": 4, "yield_pct": D("1.08")}  # 0.27 × 4
    totals = {r["year"]: r["total"] for r in s["years"]}
    assert totals[2019] == D("0.80") and totals[2025] == D("1.04") and totals[2026] == D("0.54")
    g = s["growth_5y"]
    assert g["from"] == 2020 and g["to"] == 2025
    assert abs(float(g["cagr_pct"]) - ((1.04 / 0.84) ** 0.2 - 1) * 100) < 1e-9
    assert s["increase_streak_years"] == 6  # 2020–2025 each above the year before


def test_no_dividends_and_annual_payer():
    assert dv.summary([], date(2026, 6, 30), D(10))["status"] == "none"
    s = dv.summary([(date(2025, 6, 13), D(4)), (date(2024, 7, 12), D(4))], date(2026, 6, 30), None)
    assert s["frequency"] == "annual" and s["ttm"]["total"] == 0 and s["ttm"]["yield_pct"] is None
    assert s["growth_5y"] is None and s["increase_streak_years"] == 0
    assert s["indicated"]["total"] == 4 and s["indicated"]["yield_pct"] is None
    odd = dv.summary([(date(2021, 1, 1), D(1))], date(2026, 6, 30), D(10))
    assert odd["frequency"] == "irregular" and odd["indicated"] is None


def test_dividends_api_on_sample_data(api):
    out = api.get("/api/terminal/dividends", params={"symbol": "SX:AURORA"}).json()
    assert (
        out["status"] == "available" and out["frequency"] == "annual" and out["source"] == "fixture corporate actions"
    )
    assert out["last"]["ex_date"] == "2026-06-12" and float(out["ttm"]["total"]) == 4.0
    assert abs(float(out["ttm"]["yield_pct"]) - 4 / float(out["price"]) * 100) < 1e-4  # serialised to 4 places

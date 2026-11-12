"""Provider statements for listings outside SEC coverage (docs/INDIA_FINANCIALS_PLAN.md, phase 1)."""

from datetime import date
from decimal import Decimal as D

import pandas as pd

from marketdesk.services import fin_analysis as fa
from marketdesk.services import reported
from marketdesk.services.financial_view import _quarter_gaps

FY = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-03-31"), pd.Timestamp("2024-03-31")]


def frames():
    income = pd.DataFrame(
        {FY[0]: [1000, 400, 120, 10, "nan"], FY[1]: [800, 300, 100, 9, None], FY[2]: [None, None, None, None, None]},
        index=["TotalRevenue", "OperatingIncome", "NetIncome", "DilutedEPS", "EBITDA"],
    )
    balance = pd.DataFrame(
        {FY[0]: [500, 50], FY[1]: [450, 40], FY[2]: [None, 30]}, index=["StockholdersEquity", "TotalDebt"]
    )
    cash = pd.DataFrame(
        {FY[0]: [-60, 200], FY[1]: [-50, 150], FY[2]: [-40, None]}, index=["CapitalExpenditure", "OperatingCashFlow"]
    )
    return income, balance, cash


def rows():
    out = {}
    for f in frames():
        out.update(reported.frame_rows(f))
    return out


def test_frame_rows_skip_missing_and_non_numeric_values():
    r = rows()
    assert r["TotalRevenue"] == {date(2026, 3, 31): D(1000), date(2025, 3, 31): D(800)}
    assert "EBITDA" not in r  # only NaN/None: no row at all, never a zero


def test_normalize_maps_lines_units_and_drops_sparse_periods():
    st = reported.normalize(rows(), "annual", "INR", "Provider statements", 12, 60)
    lines = {x["key"]: x for x in st["lines"]}
    # FY2024 has only two stray lines (debt, capex) out of eight: dropped rather than shown as an empty column
    assert st["period_ends"] == [date(2026, 3, 31), date(2025, 3, 31)]
    assert [v["value"] for v in lines["capex"]["values"]] == [D(60), D(50)]  # outflow shown as a positive amount
    assert lines["eps_diluted"]["values"][0]["unit"] == "INR/shares" and lines["revenue"]["values"][0]["unit"] == "INR"
    assert lines["revenue"]["values"][0]["filed"] == "2026-05-30"  # 60 days after the year end
    assert lines["ebitda"]["status"] == "unavailable" and "no annual ebitda" in lines["ebitda"]["reason"]
    assert st["origin"] == "provider" and st["taxonomy"] is None


def test_codec_round_trip_and_analysis_run_on_provider_statements():
    st = reported.from_json(reported.to_json(reported.normalize(rows(), "annual", "INR", "x", 12, 60)))
    assert st["period_ends"][0] == date(2026, 3, 31) and isinstance(st["lines"][0]["values"][0]["value"], D)
    an = fa.analysis(st)
    m = {r["key"]: r for r in an["margins"]["rows"]}
    assert m["operating_margin"]["values"][0] == D("0.4") * 100 or float(m["operating_margin"]["values"][0]) == 40


def test_quarter_gaps_name_the_skipped_quarter():
    ends = [date(2026, 9, 30), date(2026, 6, 30), date(2026, 3, 31), date(2025, 12, 31), date(2025, 6, 30)]
    st = {"lines": [{"kind": "duration", "values": [{"end": e} for e in ends]}]}
    assert _quarter_gaps(st) == [date(2025, 9, 30)]


def test_statement_currency_only_when_known():
    assert reported.statement_currency("RELIANCE.NS", None) == "INR"
    assert reported.statement_currency("TM", "JP") is None


def test_efficiency_ratios_follow_their_formulas():
    e = date(2026, 3, 31)

    def line(key, v):
        return {"key": key, "values": [{"value": D(v), "end": e, "unit": "INR"}]}

    st = {"period": "annual", "period_ends": [e], "lines": [
        line("operating_income", 200), line("total_assets", 1500), line("current_liabilities", 500),
        line("interest_expense", 40), line("current_assets", 750), line("total_debt", 300), line("equity", 600),
        line("dividends_paid", 30), line("net_income", 120), line("receivables", 73), line("revenue", 1000),
        line("inventory", 60), line("cost_of_revenue", 730), line("payables", 40),
    ]}  # fmt: skip
    rows = {r["key"]: r["values"][0] for r in fa.efficiency(st)["rows"]}
    assert rows["roce"] == 20  # 200 ÷ (1500 − 500) × 100
    assert rows["interest_coverage"] == 5 and rows["current_ratio"] == D("1.5") and rows["debt_equity"] == D("0.5")
    assert rows["payout"] == 25 and rows["debtor_days"] == D("26.645")
    assert rows["inventory_days"] == 30 and rows["payable_days"] == 20
    assert rows["cash_conversion_cycle"] == D("26.645") + 30 - 20
    assert fa.efficiency({"period": "annual", "period_ends": [e], "lines": [line("revenue", 1)]}) is None
    assert fa.efficiency({**st, "period": "quarterly"}) is None  # day counts need a full year

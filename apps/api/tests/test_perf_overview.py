"""Performance overview: period returns (hand vectors), YTD base, annualisation, gaps, 52-week range, API."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

from marketdesk.services import perf_overview as po


def daily(start: date, values):
    return [(start + timedelta(days=i), D(str(v))) for i, v in enumerate(values)]


def test_period_returns_and_ytd():
    # 6 years of daily closes rising by 1 a day from 100
    s = daily(date(2020, 1, 1), [100 + i for i in range(2200)])
    end_d, end_c = s[-1]
    r = po.period_returns(s)
    one_m = po.close_on_or_before(s, po.start_for("1M", end_d))
    assert float(r["1M"]["return_pct"]) == float((end_c / one_m[1] - 1) * 100)
    ytd_base = dict(s)[date(end_d.year - 1, 12, 31)]
    assert r["YTD"]["start"] == f"{end_d.year - 1}-12-31" and float(r["YTD"]["return_pct"]) == float(
        (end_c / ytd_base - 1) * 100
    )
    five = dict(s)[po.start_for("5Y", end_d)]
    expected_ann = ((float(end_c) / float(five)) ** 0.2 - 1) * 100
    assert abs(float(r["5Y"]["annualized_pct"]) - expected_ann) < 1e-9 and "annualized_pct" not in r["1Y"]


def test_short_history_gives_reasons_and_range():
    s = daily(date(2026, 1, 1), [10, 12, 9, 11] + [11] * 60)
    r = po.period_returns(s)
    assert r["1Y"]["return_pct"] is None and "does not reach back" in r["1Y"]["why"]
    assert r["1M"]["return_pct"] == 0
    rng = po.range_52w(s)
    assert rng["high"] == 12 and rng["low"] == 9 and rng["high_date"] == "2026-01-02"
    assert float(rng["from_high_pct"]) == float((D(11) / D(12) - 1) * 100)
    assert po.period_returns(s[:1])["1W"]["return_pct"] is None


def test_performance_api_on_sample_data(api):
    out = api.get("/api/terminal/performance", params={"symbol": "SX:AURORA"}).json()
    assert out["benchmark"]["symbol"] == "SX:SX50" and [r["code"] for r in out["rows"]][:2] == ["1W", "1M"]
    one_y = next(r for r in out["rows"] if r["code"] == "1Y")
    assert one_y["return_pct"] is not None and one_y["benchmark_pct"] is not None
    assert abs(float(one_y["relative_pct"]) - (float(one_y["return_pct"]) - float(one_y["benchmark_pct"]))) < 1e-3
    assert out["range_52w"]["high"] >= out["range_52w"]["low"] and "dividends not included" in out["note"]

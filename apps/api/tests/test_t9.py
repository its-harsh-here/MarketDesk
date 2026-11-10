"""Terminal T9: movers monitor — unusual-volume ratio on completed sessions, ranking and breadth, API on sample data."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

from marketdesk.providers.base import DailyBar
from marketdesk.services import movers as mv


def bars(vols):
    d0 = date(2026, 1, 1)
    return [DailyBar(d0 + timedelta(days=i), D(1), D(1), D(1), D(1), v) for i, v in enumerate(vols)]


def test_volume_ratio_uses_the_median_of_earlier_sessions():
    r = mv.volume_ratio(bars([100] * 10 + [200] * 10 + [450]))
    assert r["median"] == 150 and r["n"] == 20 and r["ratio"] == 3.0 and r["volume"] == 450
    assert mv.volume_ratio(bars([100] * 10)) is None  # too few sessions
    assert mv.volume_ratio(bars([None] * 30)) is None


def test_rank_and_breadth():
    rows = [
        {"symbol": "A", "change_pct": D("2.5"), "traded_value": D(10), "unusual": {"ratio": 2.0}},
        {"symbol": "B", "change_pct": D("-1"), "traded_value": D(50), "unusual": {"ratio": 1.2}},
        {"symbol": "C", "change_pct": D("0"), "traded_value": None, "unusual": None},
        {"symbol": "D", "change_pct": D("4"), "traded_value": D(5), "unusual": {"ratio": 1.6}},
        {"symbol": "E"},  # no quote
    ]
    r = mv.rank(rows)
    assert [x["symbol"] for x in r["gainers"]] == ["D", "A"] and [x["symbol"] for x in r["losers"]] == ["B"]
    assert [x["symbol"] for x in r["active"]] == ["B", "A", "D"] and [x["symbol"] for x in r["unusual"]] == ["A", "D"]
    assert r["breadth"] == {"advancing": 2, "declining": 1, "unchanged": 1, "no_quote": 1}


def test_movers_api_on_sample_data(api):
    api.post("/api/workspace/starter-watchlist")
    out = api.get("/api/terminal/movers").json()
    assert out["universe"]["members"] >= 10 and out["currencies"] == ["INR"]
    b = out["breadth"]
    assert b["advancing"] + b["declining"] + b["unchanged"] + b["no_quote"] == out["universe"]["members"]
    g = [float(x["change_pct"]) for x in out["gainers"]]
    assert g == sorted(g, reverse=True) and all(x > 0 for x in g)
    assert all(float(x["change_pct"]) < 0 for x in out["losers"])
    assert api.get("/api/terminal/movers", params={"universe": "nope"}).status_code == 422

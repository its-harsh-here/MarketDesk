"""M12: macro watchboard with provider/frequency/observation/revision, deterministic briefing, sector-relative view,
owner-entered exposure links with descriptive correlation."""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal as D

from marketdesk.providers.base import DailyBar
from marketdesk.services import macro as mc


def bars(values, end=date(2026, 6, 30)):
    d = end
    days = []
    while len(days) < len(values):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    return [DailyBar(day, v, v, v, v, None) for day, v in zip(days, values, strict=True)]


def test_series_changes_use_points_for_yields_and_percent_for_levels():
    vals = [D("4.00")] * 270 + [D("4.25")]
    y = mc.series_row(
        mc.Series("^TNX", "US 10y", "Rates", "% a year", "yield"), bars(vals), None, "available", {"provider": "yahoo"}
    )
    assert y["changes"]["1w"] == {"value": "0.25", "unit": "pp", "from": y["changes"]["1w"]["from"]}
    assert y["revision"] == "Market price: not revised" and y["frequency"].startswith("daily")
    lv = mc.series_row(
        mc.Series("BZ=F", "Brent", "Commodities", "USD per barrel", "level"),
        bars([D(80)] * 270 + [D(84)]),
        None,
        "available",
        {"provider": "yahoo"},
    )
    assert lv["changes"]["1m"]["value"] == "5.00" and lv["changes"]["1m"]["unit"] == "%"
    short = mc.series_row(mc.Series("X", "x", "FX", "u", "level"), bars([D(1)] * 10), None, "available", {})
    assert short["changes"]["1y"] is None  # no value a year ago: not substituted
    empty = mc.series_row(mc.Series("X", "x", "FX", "u", "level"), [], None, "missing", {"message": "no data"})
    assert empty["value"] is None and empty["message"] == "no data"


def test_briefing_orders_moves_and_quotes_owner_links_only():
    board = {
        "series": [
            {
                "symbol": "A",
                "name": "Alpha",
                "unit": "u",
                "provider": "p",
                "value": "10",
                "session_date": "2026-06-30",
                "changes": {"1w": {"value": "2.00", "unit": "%", "from": "2026-06-23"}},
            },
            {
                "symbol": "Y",
                "name": "Yield",
                "unit": "%",
                "provider": "p",
                "value": "4.5",
                "session_date": "2026-06-30",
                "changes": {"1w": {"value": "0.30", "unit": "pp", "from": "2026-06-23"}},
            },
            {
                "symbol": "Z",
                "name": "Zero",
                "unit": "u",
                "provider": "p",
                "value": None,
                "session_date": None,
                "changes": {},
            },
        ]
    }
    links = [{"symbol": "SX:AURORA", "series_symbol": "A", "relation": "cost", "direction": "up_hurts", "note": "fuel"}]
    b = mc.briefing(board, links)
    assert [i["series"] for i in b["items"]] == ["Y", "A"]  # 0.3 pp counts like 3%
    assert b["items"][0]["text"].startswith("Yield: +0.30 pp since 2026-06-23 to 4.5 %")
    assert b["items"][1]["linked"] == [
        {"symbol": "SX:AURORA", "relation": "cost", "direction": "up_hurts", "note": "fuel"}
    ]
    assert "nothing here states a cause" in b["note"]


def test_watchboard_api_on_sample_data(api):
    w = api.get("/api/macro/watchboard").json()
    syms = [s["symbol"] for s in w["series"]]
    assert syms == ["SX:SX50", "SX:SXFIN", "SX:USDINR"]
    s = w["series"][0]
    assert s["provider"] == "fixture" and s["status"] == "sample" and s["session_date"] == "2026-06-30"
    assert s["changes"]["1y"]["value"] is not None and len(s["spark"]) == 60
    assert {n["status"] for n in w["not_configured"]} == {"not configured", "not verified"}
    assert len(w["briefing"]["items"]) == 3


def test_sector_relative_view(api):
    wl = api.post("/api/watchlists", json={"name": "Rel"}).json()["id"]
    for sym in ("SX:AURORA", "SX:GLASSWING", "SX:NIMBUS", "SX:HALCYON"):
        api.post(f"/api/watchlists/{wl}/items", json={"symbol": sym})
    api.post("/api/screener/refresh", json={"universe": {"kind": "watchlist", "id": wl}})
    for _ in range(200):
        if not api.get("/api/screener/refresh").json()["running"]:
            break
        time.sleep(0.05)
    r = api.get("/api/macro/sector-relative", params={"kind": "watchlist", "id": wl, "metric": "return_3m_pct"}).json()
    rows = {x["symbol"]: x for x in r["rows"]}
    assert rows["SX:AURORA"]["vs_sector_pp"] is None and rows["SX:AURORA"]["sector_n"] == 1  # alone in its sector
    tech = [rows[s] for s in ("SX:GLASSWING", "SX:NIMBUS", "SX:HALCYON")]
    assert all(t["sector_n"] == 3 for t in tech)
    avg = sum(D(t["return_pct"]) for t in tech) / 3
    assert abs(D(tech[0]["vs_sector_pp"]) - (D(tech[0]["return_pct"]) - avg)) < D("0.01")
    assert rows["SX:AURORA"]["benchmark_pct"] is not None and rows["SX:HALCYON"]["benchmark_pct"] is None  # no US index
    assert api.get("/api/macro/sector-relative", params={"metric": "pe_ratio"}).status_code == 422


def test_exposure_links(api):
    r = api.post(
        "/api/macro/links",
        json={
            "symbol": "SX:AURORA",
            "series_symbol": "SX:USDINR",
            "relation": "cost",
            "direction": "up_hurts",
            "note": "imported equipment",
        },
    )
    assert r.status_code == 201, r.text
    dup = api.post(
        "/api/macro/links",
        json={"symbol": "SX:AURORA", "series_symbol": "SX:USDINR", "relation": "fx", "direction": "unclear"},
    )
    assert dup.status_code == 409
    bad = api.post(
        "/api/macro/links",
        json={"symbol": "SX:AURORA", "series_symbol": "GC=F", "relation": "fx", "direction": "unclear"},
    )
    assert bad.status_code == 422
    links = api.get("/api/macro/links", params={"with_correlation": True}).json()
    lk = links["links"][0]
    assert lk["symbol"] == "SX:AURORA" and lk["note"] == "imported equipment"
    assert (
        lk["correlation"]["method"] == "daily"
        and lk["correlation"]["n"] >= 60
        and "not evidence of cause" in links["note"]
    )
    w = api.get("/api/macro/watchboard").json()
    item = next(i for i in w["briefing"]["items"] if i["series"] == "SX:USDINR")
    assert item["linked"][0]["note"] == "imported equipment"
    assert api.delete(f"/api/macro/links/{lk['id']}").status_code == 204
    assert api.get("/api/macro/links").json()["links"] == []


def test_links_are_backed_up():
    from marketdesk.services.backup import backup_tables

    assert "macro_links" in {t.name for t in backup_tables()}

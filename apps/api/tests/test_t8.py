"""Terminal T8: FRED client (key validation, no key in errors), official-series summaries (level, change,
year-on-year, vintage), release calendar filtering, the not-configured path, the context strip's correlation and
changes, and the context API on sample data."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from marketdesk.api.app import create_app
from marketdesk.db import db_session
from marketdesk.providers.base import ProviderError
from marketdesk.providers.fred import FredClient
from marketdesk.services import context as cx
from marketdesk.services import official as of

from .conftest import make_settings, migrated

KEY = "abcdef0123456789abcdef0123456789"


def test_fred_key_validation_and_errors_never_echo_the_key(monkeypatch):
    assert not FredClient(None).enabled and "FRED_API_KEY" in FredClient(None).problem
    assert not FredClient("short").enabled and "32-character" in FredClient("short").problem
    c = FredClient(KEY)
    assert c.enabled

    import urllib.error

    def boom(req, timeout=None):
        assert KEY in req.full_url  # FRED takes the key as a query parameter
        raise urllib.error.HTTPError(req.full_url, 500, "x", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(ProviderError) as e:
        c.series("UNRATE")
    assert KEY not in e.value.message and "HTTP 500" in e.value.message
    with pytest.raises(ProviderError, match="series id"):
        c.observations("bad id!", "2020-01-01")


def obs(values, start=date(2024, 1, 1), months=True, vintage="2026-11-07"):
    out, d = [], start
    for v in values:
        out.append({"date": d.isoformat(), "value": v, "realtime_start": vintage})
        d = date(d.year + (d.month // 12), d.month % 12 + 1, 1) if months else d + timedelta(days=1)
    return out


def test_summarise_level_change_yoy_and_missing():
    cpi = of.OfficialSeries("CPIAUCSL", "CPI", "index", "yoy")
    vals = [str(100 + i) for i in range(14)]  # Jan 2024 … Feb 2025 = 113
    r = of.summarise(cpi, {"frequency": "Monthly", "last_updated": "2026-11-07"}, obs(vals))
    assert r["date"] == "2025-02-01" and r["value"] == D(113) and r["change"] == D(1)
    assert r["yoy_pct"] == (D(113) / D(101) - 1) * 100 and r["previous_yoy_pct"] == (D(112) / D(100) - 1) * 100
    assert r["vintage"] == "2026-11-07" and r["url"].endswith("/CPIAUCSL")
    un = of.OfficialSeries("UNRATE", "Unemployment", "%", "level")
    r2 = of.summarise(un, {}, obs(["4.1", ".", "4.3"]))  # "." is FRED's missing value
    assert r2["value"] == D("4.3") and r2["previous"]["value"] == D("4.1") and "yoy_pct" not in r2
    assert of.summarise(un, {}, [])["value"] is None


def test_release_calendar_keeps_market_moving_releases_from_today():
    rows = [
        {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-11-13"},
        {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-11-13"},
        {"release_id": 50, "release_name": "Employment Situation", "date": "2026-11-06"},  # before today
        {"release_id": 18, "release_name": "H.15 Selected Interest Rates", "date": "2026-11-12"},
        {"release_id": 53, "release_name": "Gross Domestic Product", "date": "2026-11-26"},
    ]
    cal = of.upcoming(rows, date(2026, 11, 11))
    assert [(c["date"], c["release"]) for c in cal] == [("2026-11-13", "Consumer Price Index"),
                                                        ("2026-11-26", "Gross Domestic Product")]  # fmt: skip


def test_official_not_configured_explains_how(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))
    create_app(s)
    with db_session() as db:
        out = asyncio.run(of.official(db, FredClient(None), date(2026, 11, 11)))
    assert out["status"] == "not_configured" and "FRED_API_KEY" in out["how"]


def test_official_with_a_fake_fred_is_cached(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))
    create_app(s)

    class Fake(FredClient):
        calls = 0

        def series(self, sid):
            Fake.calls += 1
            return {"id": sid, "frequency": "Monthly", "last_updated": "2026-11-07 07:46:02-06"}

        def observations(self, sid, start):
            return obs([str(100 + i) for i in range(14)])

        def release_dates(self, start, end, limit=200):
            return [{"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-11-13"}]

    f = Fake(KEY)
    with db_session() as db:
        a = asyncio.run(of.official(db, f, date(2026, 11, 11)))
        b = asyncio.run(of.official(db, f, date(2026, 11, 11)))
    assert (
        a["status"] == "available" and len(a["series"]) == len(of.SERIES) and a["calendar"][0]["date"] == "2026-11-13"
    )
    assert Fake.calls == len(of.SERIES) and b["series"] == a["series"]  # second call from the cache
    assert "FRED" in a["attribution"]


def test_context_correlation_and_changes():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(80)]
    a = {d: D(100) * D("1.01") ** (i % 2) for i, d in enumerate(days)}
    b = {d: D(50) * D("1.02") ** (i % 2) for i, d in enumerate(days)}  # moves with a
    c = {d: D(10) * D("1.01") ** ((i + 1) % 2) for i, d in enumerate(days)}  # moves against a
    assert cx.correlation(a, b)[0] == pytest.approx(1.0) and cx.correlation(a, c)[0] == pytest.approx(-1.0, abs=1e-9)
    assert cx.correlation(dict(list(a.items())[:20]), b) == (None, 19)
    y = {days[0]: D("4.00"), days[-31]: D("4.10"), days[-2]: D("4.20"), days[-1]: D("4.35")}
    ch = cx.changes(y, "yield")
    assert ch["d1"] == pytest.approx(0.15) and ch["m1"] == pytest.approx(0.25)  # percentage points


def test_context_api_on_sample_data(api):
    out = api.get("/api/terminal/context", params={"symbol": "SX:AURORA"}).json()
    syms = [i["symbol"] for i in out["items"]]
    assert syms == ["SX:SX50", "SX:USDINR"]
    bench = out["items"][0]
    assert bench["value"] is not None and bench["n"] >= 60 and -1 <= bench["correlation"] <= 1
    off = api.get("/api/macro/official").json()
    assert off["status"] == "not_configured"

"""Terminal T6: risk and relative value — hand vectors for beta/correlation, drawdown episodes, spread estimate and
z-scores; FINRA client token and query flow (fake HTTP); short interest gated on credentials; API on sample data."""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from marketdesk.providers import finra as fin
from marketdesk.services import security_risk as sr


def closes_from(returns, start=date(2026, 1, 1), base=D(100)):
    out, v, d = {start: base}, base, start
    for r in returns:
        d += timedelta(days=1)
        v = v * (1 + D(str(r)))
        out[d] = v
    return out


def test_beta_correlation_daily_and_weekly():
    b_ret = [0.01 if i % 2 else -0.005 for i in range(90)]
    b = closes_from(b_ret)
    a = closes_from([2 * r for r in b_ret])
    s = sr.sensitivity(a, b, True)
    assert s["method"] == "daily" and s["n"] == 90
    assert abs(s["beta"] - 2) < 0.05 and s["correlation"] > 0.999 and abs(s["r2"] - s["correlation"] ** 2) < 1e-12
    w = sr.sensitivity(a, b, False)
    assert w["method"] == "weekly" and w["beta"] is None and "26" in w["why"]  # 13 weeks is too few


def test_drawdown_episodes_and_profile():
    days = [date(2026, 1, i) for i in range(1, 8)]
    vals = [100, 120, 90, 110, 125, 100, 130]
    eps = sr.episodes(list(zip(days, map(float, vals), strict=True)))
    assert [round(e["depth"], 4) for e in eps] == [-0.25, -0.2]
    assert eps[0]["peak"] == days[1] and eps[0]["trough"] == days[2] and eps[0]["recovered"] == days[4]
    assert eps[0]["days_to_trough"] == 1 and eps[0]["days_to_recover"] == 2
    ongoing = sr.episodes([(days[0], 100.0), (days[1], 80.0), (days[2], 90.0)])
    assert ongoing[0]["recovered"] is None and ongoing[0]["days_to_recover"] is None
    prof = sr.drawdown_profile({d: D(v) for d, v in zip(days, vals, strict=True)})
    assert prof["current"] == 0.0 and prof["windows"]["1Y"]["why"]  # a week of data is shorter than a year


@dataclass
class Bar:
    session_date: date
    close: D
    high: D
    low: D
    volume: int | None


def test_liquidity_and_daily_range():
    flat = [Bar(date(2026, 1, 1) + timedelta(days=i), D(10), D(10), D(10), 1000 + i) for i in range(60)]
    liq = sr.liquidity(flat)
    assert liq["adv_20"] == D(sum(1000 + i for i in range(40, 60))) / 20 and liq["median_range_pct"] == 0.0
    assert liq["value_20"] == liq["adv_20"] * 10
    ranged = [Bar(date(2026, 1, 1) + timedelta(days=i), D(100), D(101 + i % 3), D(99), 10) for i in range(21)]
    assert abs(sr.daily_range(ranged) - 0.03) < 1e-12  # ranges 2%, 3%, 4% repeating → median 3%
    assert sr.daily_range(flat[:10]) is None  # too few sessions


def test_zscores_within_a_universe():
    uni = [{"pe_ratio": {"v": str(x)}} for x in (1, 2, 3, 4, 5)]
    row = sr.zscores({"pe_ratio": {"v": "5"}}, uni, keys=("pe_ratio",))[0]
    assert row["mean"] == 3 and abs(float(row["z"]) - 1.2649) < 1e-4 and row["percentile"] == 100 and row["n"] == 5
    few = sr.zscores({"pe_ratio": {"v": "5"}}, uni[:3], keys=("pe_ratio",))[0]
    assert "at least 5" in few["why"]
    missing = sr.zscores({"pe_ratio": {"v": None, "why": "Negative earnings."}}, uni, keys=("pe_ratio",))[0]
    assert missing["why"] == "Negative earnings."


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_finra_client_token_query_and_fallback(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req)
        if "oauth2" in req.full_url:
            return FakeResp(json.dumps({"access_token": "tok", "expires_in": "43170"}).encode())
        body = json.loads(req.data)
        if body["compareFilters"][0]["compareType"] == "EQUAL":
            import urllib.error

            raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)
        rows = [{"settlementDate": "2026-09-30", "currentShortPositionQuantity": 10},
                {"settlementDate": "2026-10-15", "currentShortPositionQuantity": 12}]  # fmt: skip
        return FakeResp(json.dumps(rows).encode())

    monkeypatch.setattr(fin.urllib.request, "urlopen", fake_urlopen)
    c = fin.FinraClient("id1", "sec2")
    rows = c.short_interest("aapl")
    assert [r["settlementDate"] for r in rows] == ["2026-10-15", "2026-09-30"]  # newest first
    tok = seen[0]
    assert (
        tok.get_method() == "POST" and tok.headers["Authorization"] == "Basic " + base64.b64encode(b"id1:sec2").decode()
    )
    data = seen[-1]
    assert data.headers["Authorization"] == "Bearer tok" and data.headers["Accept"] == "application/json"
    flt = json.loads(data.data)["compareFilters"][0]
    assert flt == {"compareType": "equal", "fieldName": "symbolCode", "fieldValue": "AAPL"}
    c.short_interest("aapl")
    assert sum("oauth2" in r.full_url for r in seen) == 1  # token cached


def test_short_interest_is_gated_on_credentials():
    class Inst:
        country, symbol = "US", "AAPL"

    out = sr._short_interest(None, fin.FinraClient(None, None), Inst())
    assert out["status"] == "not_configured" and "FINRA_CLIENT_ID" in out["reason"]
    Inst.country = "IN"
    assert sr._short_interest(None, fin.FinraClient("a", "b"), Inst())["status"] == "not_applicable"


def test_risk_api_on_sample_data(api):
    r = api.get("/api/terminal/risk", params={"symbol": "SX:AURORA"}).json()
    assert r["benchmark"]["symbol"] == "SX:SX50" and r["benchmark"]["same_market"] is True
    one = r["sensitivity"]["1Y"]
    assert one["method"] == "daily" and one["beta"] is not None and one["n"] >= 200
    assert r["volatility"]["1Y"]["value"] is not None and r["drawdowns"]["episodes"]
    assert r["liquidity"]["adv_20"] is not None and r["liquidity"]["median_range_pct"] is not None
    assert r["relative"]["universe"]["label"] == "All watchlists" and all(x["why"] for x in r["relative"]["rows"])
    assert r["short_interest"]["status"] == "not_applicable"
    assert api.get("/api/terminal/risk", params={"symbol": "SX:AURORA", "universe": "bogus"}).status_code == 422
    b = api.get("/api/terminal/risk", params={"symbol": "SX:AURORA", "benchmark": "SX:BANYAN"}).json()
    assert b["benchmark"]["symbol"] == "SX:BANYAN"


@pytest.mark.parametrize("bad", ["", "list:x"])
def test_universe_param_is_validated(api, bad):
    assert api.get("/api/terminal/risk", params={"symbol": "SX:AURORA", "universe": bad}).status_code == 422

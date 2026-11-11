"""Terminal T7: option chain analytics (max pain, put/call ratios, ATM IV hand vectors), Yahoo chain
normalisation, cache round trip, India gate, API on sample data."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pandas as pd

from marketdesk.providers.base import OptionChain, OptionQuote
from marketdesk.providers.serialize import CODECS
from marketdesk.providers.yahoo import _option_rows
from marketdesk.services import options as op


def q(strike, oi, iv="0.3", vol=10):
    return OptionQuote(f"X{strike}", D(strike), D(1), None, None, vol, oi, D(iv), None, None)


def test_max_pain_ratios_and_atm():
    calls = [q(90, 100), q(100, 300), q(110, 50)]
    puts = [q(90, 80), q(100, 200, "0.5"), q(110, 400)]
    # payouts: S=90 → puts (100−90)·200 + (110−90)·400 = 10000; S=100 → calls 10·100 + puts 10·400 = 5000;
    #          S=110 → calls 20·100 + 10·300 = 5000 + puts 0 → 5000 (tie: the lower strike)
    assert op.max_pain(calls, puts) == D(100)
    chain = OptionChain([date(2026, 7, 17)], date(2026, 7, 17), calls, puts, "USD", "test")
    a = op.analytics(chain, D("101"))
    assert a["calls"]["open_interest"] == 450 and a["puts"]["open_interest"] == 680
    assert a["put_call_oi"] == D(680) / D(450) and a["put_call_volume"] == 1
    assert a["atm"] == {"strike": D(100), "iv": D("0.4")}  # mean of the call 0.3 and put 0.5 at the nearest strike
    assert op.ratio(5, 0) is None and op.max_pain([], []) is None


def test_yahoo_rows_and_cache_round_trip():
    df = pd.DataFrame([
        {"contractSymbol": "AAPL260717C00200000", "lastTradeDate": pd.Timestamp("2026-07-10 19:59", tz="UTC"),
         "strike": 200.0, "lastPrice": 12.5, "bid": 12.4, "ask": 12.6, "volume": float("nan"), "openInterest": 1500,
         "impliedVolatility": 0.27, "inTheMoney": True, "currency": "USD"},
        {"contractSymbol": "AAPL260717C00190000", "strike": 190.0, "lastPrice": 20.0, "openInterest": 10,
         "impliedVolatility": 0.3, "inTheMoney": True},
    ])  # fmt: skip
    rows = _option_rows(df)
    assert [r.strike for r in rows] == [D(190), D(200)]  # sorted by strike
    r = rows[1]
    assert r.volume is None and r.open_interest == 1500 and r.implied_vol == D("0.27")
    assert r.last_trade == datetime(2026, 7, 10, 19, 59, tzinfo=UTC)
    chain = OptionChain([date(2026, 7, 17)], date(2026, 7, 17), rows, rows, "USD", "Yahoo")
    enc, dec = CODECS["options"]
    assert dec(enc(chain)) == chain


def test_options_api_on_sample_data(api):
    out = api.get("/api/terminal/options", params={"symbol": "SX:HALCYON"}).json()
    assert out["source"] == "Sample option chain (fictitious)" and len(out["expiries"]) == 4
    assert out["expiry"] == out["expiries"][0] and len(out["calls"]) == len(out["puts"]) > 10
    st = out["stats"]
    assert float(st["put_call_oi"]) > 0 and st["max_pain"] is not None and st["atm"]["iv"] is not None
    later = api.get("/api/terminal/options", params={"symbol": "SX:HALCYON", "expiry": out["expiries"][2]}).json()
    assert later["expiry"] == out["expiries"][2]
    # call prices fall as the strike rises (a basic sanity check of the sample chain)
    lasts = [float(c["last"]) for c in out["calls"]]
    assert lasts == sorted(lasts, reverse=True)
    india = api.get("/api/terminal/options", params={"symbol": "SX:AURORA"}).json()
    assert india["status"] == "not_available" and "NSE" in india["reason"]

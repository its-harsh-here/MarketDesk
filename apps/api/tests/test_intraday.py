"""Intraday 1D/5D: Yahoo bar normalisation (UTC, ascending, de-duplicated, empty closes dropped), cache codec round
trip, the fixture's deterministic in-range sample path, and the API on sample data."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D

import pandas as pd
import pytest

from marketdesk.providers.base import ProviderError
from marketdesk.providers.serialize import CODECS
from marketdesk.providers.yahoo import normalize_intraday


def test_normalize_intraday_utc_sorted_and_clean():
    idx = pd.DatetimeIndex(["2026-11-11 09:35", "2026-11-11 09:30", "2026-11-11 09:35", "2026-11-11 09:40"],
                           tz="America/New_York")  # fmt: skip
    df = pd.DataFrame({"Open": [10, 9.5, 10.1, 11], "High": [10.5, 10, 10.6, 11], "Low": [9.9, 9.4, 10, 11],
                       "Close": [10.2, 9.8, 10.4, float("nan")], "Volume": [100, 200, 300, 0]}, index=idx)  # fmt: skip
    bars = normalize_intraday(df, 2, False)
    assert [b.time for b in bars] == [
        datetime(2026, 11, 11, 14, 30, tzinfo=UTC),
        datetime(2026, 11, 11, 14, 35, tzinfo=UTC),
    ]
    assert bars[1].close == D("10.40") and bars[1].volume == 300  # duplicate instant: last row wins
    assert normalize_intraday(pd.DataFrame(), 2, False) == []
    with pytest.raises(ProviderError):
        normalize_intraday(pd.DataFrame({"Open": [1]}, index=idx[:1]), 2, False)


def test_intraday_codec_and_fixture_path(app):
    provider = app.state.market.provider
    sym = next(iter(provider.dataset.instruments))
    h = provider.intraday(sym, "1D")
    assert h.interval == "5m" and len(h.bars) == 75 and h.previous_close is not None
    day = provider._bars_to_cursor(sym)[-1]
    assert h.bars[-1].close == day.close.quantize(D("0.01"))
    assert all(day.low - D("0.01") <= b.close <= day.high + D("0.01") for b in h.bars)
    assert [b.time for b in h.bars] == sorted(b.time for b in h.bars)
    five = provider.intraday(sym, "5D")
    assert five.interval == "15m" and len(five.bars) == 125 and five.previous_close is None
    enc, dec = CODECS["intraday"]
    assert dec(enc(h)) == h


def test_intraday_api_on_sample_data(api):
    out = api.get("/api/market/intraday", params={"symbol": "SX:HALCYON", "range": "1D"}).json()
    assert out["interval"] == "5m" and len(out["bars"]) == 75 and out["meta"]["status"] in ("sample", "available")
    assert out["bars"][0]["time"] < out["bars"][-1]["time"] and "Regular-session" in out["note"]
    assert api.get("/api/market/intraday", params={"symbol": "SX:HALCYON", "range": "1W"}).status_code == 422

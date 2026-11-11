"""Alpaca (docs/DECISIONS.md #65): option chain normalisation, symbol gating, credential checks, the IEX stream hub's
duplicate / out-of-order / cancel / correction handling, a full fake-websocket session with REST seeding, and the
stream endpoint when streaming is off."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from marketdesk.providers.alpaca import OPTIONS_SOURCE, AlpacaClient, normalize_chain, oi_date, us_symbol
from marketdesk.providers.base import OptionChain, OptionQuote, ProviderError
from marketdesk.services import options as op
from marketdesk.services.stream import QuoteStreamHub

KID, SEC = "PKTESTKEY1234567890AB", "s" * 40


def contract(sym, side, strike, exp="2026-11-20", oi="120", oi_day="2026-11-09"):
    return {"symbol": sym, "type": side, "strike_price": strike, "expiration_date": exp, "open_interest": oi,
            "open_interest_date": oi_day}  # fmt: skip


def snap(bid, ask, last, vol, bar_day="2026-11-11", iv=None):
    s = {"latestQuote": {"bp": bid, "ap": ask, "t": "2026-11-11T17:31:10.025987312Z"},
         "latestTrade": {"p": last, "t": "2026-11-11T17:10:53.965385589Z"},
         "dailyBar": {"v": vol, "t": f"{bar_day}T05:00:00Z"}}  # fmt: skip
    if iv is not None:
        s["impliedVolatility"] = iv
    return s


def test_symbol_gate_and_credentials():
    assert us_symbol("aapl") == "AAPL" and us_symbol("BRK-B") == "BRK.B"
    assert us_symbol("RELIANCE.NS") is None and us_symbol("^GSPC") is None and us_symbol("SX:HALCYON") is None
    assert us_symbol("EURUSD=X") is None
    assert not AlpacaClient(None, None).enabled and "not configured" in AlpacaClient(None, None).problem
    assert not AlpacaClient("bad key", SEC).enabled
    c = AlpacaClient(KID, SEC)
    assert c.enabled and c.credentials() == (KID, SEC)
    with pytest.raises(ProviderError):
        AlpacaClient(None, None).credentials()


def test_normalize_chain():
    contracts = [
        contract("X261120C00100000", "call", "100"), contract("X261120P00100000", "put", "100", oi="300"),
        contract("X261120C00110000", "call", "110", oi=None), contract("X261218C00100000", "call", "100",
                                                                      exp="2026-12-18", oi_day="2026-11-10"),
    ]  # fmt: skip
    snaps = {
        "X261120C00100000": snap(5.1, 5.3, 5.2, 40, iv=0.31),
        "X261120P00100000": snap(0.0, 0.0, 0.4, 7, bar_day="2026-11-06"),  # stale bar: not today's volume
    }
    ch = normalize_chain(contracts, snaps, date(2026, 11, 20), D("104"))
    assert ch.expiries == [date(2026, 11, 20), date(2026, 12, 18)] and ch.source == OPTIONS_SOURCE
    assert [o.strike for o in ch.calls] == [D(100), D(110)] and len(ch.puts) == 1
    c, p, bare = ch.calls[0], ch.puts[0], ch.calls[1]
    assert (c.bid, c.ask, c.last, c.volume, c.open_interest, c.implied_vol) == (D("5.1"), D("5.3"), D("5.2"), 40,
                                                                               120, D("0.31"))  # fmt: skip
    assert c.in_the_money is True and p.in_the_money is False
    assert p.ask is None and p.bid == D(0) and p.volume is None and p.open_interest == 300
    assert bare.last is None and bare.open_interest is None and bare.volume is None  # no snapshot: nothing invented
    assert c.last_trade == datetime(2026, 11, 10 + 1, 17, 10, 53, 965385, tzinfo=UTC)
    assert oi_date(contracts, date(2026, 11, 20)) == "2026-11-09"
    assert normalize_chain(contracts, snaps, date(2026, 11, 20), None).calls[0].in_the_money is None


class FakeAlpaca:
    enabled = True

    def __init__(self, fail: str | None = None):
        self.fail = fail

    def option_chain(self, symbol, expiry, spot):
        if self.fail:
            raise ProviderError("upstream_unavailable", self.fail)
        rows = [OptionQuote("C1", D(100), D(1), D(1), D("1.1"), 5, 10, D("0.3"), True, None)]
        return OptionChain([date(2026, 11, 20)], date(2026, 11, 20), rows, rows, "USD", OPTIONS_SOURCE), "2026-11-09"


class Inst:
    def __init__(self, symbol, exchange="NASDAQ", currency="USD"):
        self.symbol, self.exchange, self.currency, self.country = symbol, exchange, currency, "US"


def test_chain_view_prefers_alpaca_and_falls_back(app):
    market = app.state.market
    inst = Inst("SX:HALCYON")
    out = asyncio.run(op.chain_view(market, inst, None, FakeAlpaca()))  # fixture names are never sent to Alpaca
    assert out["source"].startswith("Sample") and out["fallback_reason"] is None

    async def us_view(alpaca):
        orig = market.options

        async def none(symbol, expiry):
            return await orig("SX:HALCYON", expiry)

        market.options = none
        try:
            return await op.chain_view(market, Inst("AAPL"), None, alpaca)
        finally:
            market.options = orig

    ok = asyncio.run(us_view(FakeAlpaca()))
    assert ok["source"] == OPTIONS_SOURCE and ok["open_interest_date"] == "2026-11-09" and "not the official OPRA" in (
        ok["note"]
    )  # fmt: skip
    down = asyncio.run(us_view(FakeAlpaca(fail="Alpaca did not respond with valid data.")))
    assert down["source"].startswith("Sample") and down["fallback_reason"].startswith("Alpaca did not respond")


def test_hub_drops_duplicates_out_of_order_and_applies_corrections():
    hub = QuoteStreamHub(AlpacaClient(KID, SEC))
    t0 = "2026-11-11T17:00:00.123456789Z"
    assert hub.ingest_trade("AAPL", 100.0, 5, t0, 1)
    assert not hub.ingest_trade("AAPL", 100.0, 5, t0, 1)  # duplicate id
    assert not hub.ingest_trade("AAPL", 99.0, 5, "2026-11-11T16:59:59Z", 2)  # older than the shown trade
    assert not hub.ingest_trade("AAPL", None, 5, t0, 3) and not hub.ingest_trade("AAPL", 101, 5, "nope", 4)
    assert hub.ingest_trade("AAPL", 101.0, 1, "2026-11-11T17:00:01Z", 5)
    assert hub.counters["duplicate"] == 1 and hub.counters["out_of_order"] == 1 and hub.counters["malformed"] == 2
    hub.handle({"T": "c", "S": "AAPL", "oi": 5, "cp": 100.5, "ci": 6})
    assert hub.ticks["AAPL"].price == 100.5 and hub.ticks["AAPL"].trade_id == 6
    hub.handle({"T": "x", "S": "AAPL", "i": 6})
    ticks, seq = hub.since(0, {"AAPL"})
    assert ticks[0]["cancelled"] is True and seq == hub.seq
    assert hub.since(seq, {"AAPL"})[0] == []
    assert hub.ingest_trade("AAPL", 99.0, 1, "2026-11-11T16:00:00Z", 7)  # after a cancel any valid trade is shown
    hub2 = QuoteStreamHub(AlpacaClient(KID, SEC))
    hub2.refs.update({f"S{i}": 1 for i in range(30)})
    hub2._ensure_task = lambda: None
    assert hub2.acquire(["S1", "NEW"]) == (["S1"], ["NEW"])  # 30-symbol plan limit


class FakeWS:
    def __init__(self, script):
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        for m in script:
            self.inbox.put_nowait(json.dumps(m))
        self.closed = False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        return await self.inbox.get()

    async def close(self):
        self.closed = True


def test_hub_session_authenticates_subscribes_seeds_and_reconnects(monkeypatch):
    client = AlpacaClient(KID, SEC)
    monkeypatch.setattr(client, "latest_trades", lambda syms: {"AAPL": {"p": 200.0, "s": 1, "t": "2026-11-11T17:00:00Z",
                                                                         "i": 1}})  # fmt: skip
    sockets: list[FakeWS] = []

    async def connect(url):
        ws = FakeWS([[{"T": "success", "msg": "connected"}], [{"T": "success", "msg": "authenticated"}]])
        sockets.append(ws)
        return ws

    async def scenario():
        hub = QuoteStreamHub(client, connect=connect)
        hub.acquire(["AAPL"])
        for _ in range(50):
            await asyncio.sleep(0.01)
            if hub.status == "live":
                break
        assert hub.status == "live" and hub.ticks["AAPL"].price == 200.0  # REST seed fills the gap
        ws = sockets[0]
        assert ws.sent[0] == {"action": "auth", "key": KID, "secret": SEC}
        assert ws.sent[1] == {"action": "subscribe", "trades": ["AAPL"]}
        ws.inbox.put_nowait(json.dumps([{"T": "t", "S": "AAPL", "p": 201.5, "s": 3, "t": "2026-11-11T17:00:02Z",
                                         "i": 2}, {"T": "t", "S": "AAPL", "p": 1.0, "s": 3,
                                                   "t": "2026-11-11T16:00:00Z", "i": 3}]))  # fmt: skip
        await asyncio.sleep(1.2)
        assert hub.ticks["AAPL"].price == 201.5 and hub.counters["out_of_order"] == 1
        ws.inbox.put_nowait(json.dumps([{"T": "error", "code": 500, "msg": "internal error"}]))
        for _ in range(400):
            await asyncio.sleep(0.01)
            if len(sockets) == 2 and hub.status == "live":
                break
        assert len(sockets) == 2 and hub.counters["reconnect"] == 1 and ws.closed
        hub.release(["AAPL"])
        hub._task.cancel()

    asyncio.run(scenario())


def test_stream_endpoint_off_in_fixture_mode(api):
    st = api.get("/api/stream/status").json()
    assert st["available"] is False and st["feed"] == "iex" and "not available" in st["reason"]
    with api.c.stream("GET", "/api/stream/quotes", params={"symbols": "AAPL,RELIANCE.NS"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert body.startswith("event: status") and '"status":"off"' in body and '"polled":["AAPL","RELIANCE.NS"]' in body


def test_us_movers_filter_and_actives_join():
    from marketdesk.services.us_market import actives_view, filter_movers

    raw = {"gainers": [{"symbol": "NXXT", "price": 2.75, "percent_change": 1374.5, "change": 2.5},
                       {"symbol": "PARAW", "price": 9.0, "percent_change": 120.0},
                       {"symbol": "BRK.B", "price": 580.0, "percent_change": 3.1, "change": 17.4},
                       {"symbol": "CRWX", "price": 7.94, "percent_change": 53.0}],
           "losers": [{"symbol": "ENGS", "price": 0.69, "percent_change": -86.0}],
           "last_updated": "2026-11-11T18:03Z"}  # fmt: skip
    m = filter_movers(raw)
    assert [r["symbol"] for r in m["gainers"]] == ["BRK.B", "CRWX"]  # no penny stock, no warrant
    assert m["losers"] == [] and m["as_of"] == "2026-11-11T18:03Z"
    act = {"most_actives": [{"symbol": "NVDA", "volume": 177_000_000, "trade_count": 2_800_000},
                            {"symbol": "SHFS", "volume": 2_000_000_000}, {"symbol": "ZZZZ", "volume": 5}]}  # fmt: skip
    snaps = {"NVDA": {"latestTrade": {"p": 176.0}, "prevDailyBar": {"c": 160.0}},
             "SHFS": {"latestTrade": {"p": 0.05}, "prevDailyBar": {"c": 0.04}}}  # fmt: skip
    rows = actives_view(act, snaps)
    assert len(rows) == 1 and rows[0]["symbol"] == "NVDA" and rows[0]["change_pct"] == 10.0


def test_alpaca_news_items_flag_broad_stories():
    from marketdesk.services.news_stream import alpaca_item

    when = datetime(2026, 11, 11, 17, 55, tzinfo=UTC)
    one = alpaca_item({"title": "Apple story", "publisher": "Benzinga", "url": "https://x/1", "published_at": when,
                       "symbols": ["AAPL", "NVDA"]}, "AAPL")  # fmt: skip
    assert one["related"] == ["NVDA"] and not one["broad"] and one["at"] == when.isoformat()
    many = alpaca_item({"title": "Market wrap", "publisher": "Benzinga", "url": None, "published_at": None,
                        "symbols": ["AAPL", "A", "B", "C", "D", "E", "F", "G"]}, "AAPL")  # fmt: skip
    assert many["broad"] and len(many["related"]) == 6 and many["precision"] == "unknown"


def test_headline_relevance_terms_and_matching():
    from types import SimpleNamespace as NS

    from marketdesk.services.news_stream import about, name_terms

    assert name_terms(NS(symbol="AAPL", name="Apple Inc.")) == ["AAPL", "Apple"]
    assert name_terms(NS(symbol="RELIANCE.NS", name="Reliance Industries Limited")) == ["RELIANCE", "Reliance"]
    assert name_terms(NS(symbol="NVDA", name="NVIDIA Corporation")) == ["NVDA", "NVIDIA"]
    apple = name_terms(NS(symbol="AAPL", name="Apple Inc."))
    assert about("Cramer says Apple investors missed gains", apple, "AAPL")
    assert about("AAPL slips after the close", apple, "AAPL")
    assert not about("Is Dell stock priced right against its peers?", apple, "AAPL")
    assert not about("Pineapple prices rise", apple, "AAPL")  # whole words only
    smr = name_terms(NS(symbol="SMR", name="NuScale Power Corporation"))
    assert about("NuScale is still down 61%", smr, "SMR")
    assert not about("Nuclear smr approval lifts the sector", smr, "SMR")  # ticker counts only in capitals
    assert about("Nvidia removed as a top pick", name_terms(NS(symbol="NVDA", name="NVIDIA Corporation")), "NVDA")

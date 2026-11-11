"""Streaming US trades from Alpaca's IEX feed (roadmap M04; docs/DECISIONS.md #65).

One websocket per web process carries the union of symbols that open browser pages ask for; pages receive the
latest trade per symbol over Server-Sent Events, at most once a second. The connection opens on the first
subscriber and closes about a minute after the last one leaves.

Truthfulness rules:
* IEX is a single exchange, not consolidated (SIP) data: every payload names the feed, and the UI says so.
* Duplicates (same trade id) and out-of-order trades (older than the one already shown) are dropped and counted.
* A disconnect is a visible state ("reconnecting"); the page falls back to its normal polled quotes meanwhile. After
  every (re)connect the latest trade per symbol is re-read over REST, so a trade missed during the gap is not shown
  as current when a newer one exists. Trade cancels and corrections from the feed are applied to the shown trade.
* Indian listings, indices and fixture names are never streamed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from marketdesk.providers.alpaca import STREAM_IEX, AlpacaClient, _ts, us_symbol

log = logging.getLogger("marketdesk.stream")

FEED = "iex"
FEED_LABEL = "single-exchange trades (IEX), not consolidated"
MAX_SYMBOLS = 30  # Alpaca's free plan allows 30 symbols on one connection
IDLE_CLOSE_SECONDS = 60.0


@dataclass
class Tick:
    symbol: str
    price: float
    size: int | None
    time: datetime
    trade_id: int | None
    seq: int
    cancelled: bool = False

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "price": self.price, "size": self.size, "time": self.time.isoformat(),
                "cancelled": self.cancelled}  # fmt: skip


class QuoteStreamHub:
    def __init__(self, client: AlpacaClient, *, enabled: bool = True, connect=None, url: str = STREAM_IEX):
        self.client = client
        self.enabled = enabled
        self.url = url
        self._connect = connect
        self.ticks: dict[str, Tick] = {}
        self.refs: Counter[str] = Counter()
        self.seq = 0
        self.status = "idle"
        self.message: str | None = None
        self.status_seq = 0
        self.connected_at: datetime | None = None
        self.counters: Counter[str] = Counter()
        self._task: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self._subscribed: set[str] = set()

    # ---- availability and subscriptions -------------------------------------------------------------------------
    def unavailable_reason(self) -> str | None:
        if not self.enabled:
            return "Live trades are not available in this deployment."
        if not self.client.enabled:
            return self.client.problem or "The live-data service is not configured."
        return None

    def acquire(self, symbols: list[str]) -> tuple[list[str], list[str]]:
        """Register interest; returns (streamed, refused-over-limit). Starts the connection task if needed."""
        streamed: list[str] = []
        refused: list[str] = []
        for s in dict.fromkeys(symbols):
            if s in self.refs or len(self.refs) < MAX_SYMBOLS:
                self.refs[s] += 1
                streamed.append(s)
            else:
                refused.append(s)
        if streamed:
            self._ensure_task()
        return streamed, refused

    def release(self, symbols: list[str]) -> None:
        for s in symbols:
            self.refs[s] -= 1
            if self.refs[s] <= 0:
                del self.refs[s]
        self._poke()

    def since(self, seq: int, symbols: set[str]) -> tuple[list[dict], int]:
        out = [t.as_dict() for t in self.ticks.values() if t.seq > seq and t.symbol in symbols]
        return out, self.seq

    def snapshot_status(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "feed": FEED,
            "feed_label": FEED_LABEL,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "symbols": len(self.refs),
            "max_symbols": MAX_SYMBOLS,
            "dropped_duplicates": self.counters["duplicate"],
            "dropped_out_of_order": self.counters["out_of_order"],
            "reconnects": self.counters["reconnect"],
        }

    def _set_status(self, status: str, message: str | None = None) -> None:
        if (status, message) != (self.status, self.message):
            self.status, self.message = status, message
            self.status_seq += 1

    def _poke(self) -> None:
        if self._wake is not None:
            self._wake.set()

    def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._wake = asyncio.Event()
            self._task = asyncio.get_running_loop().create_task(self._run(), name="alpaca-iex-stream")
        else:
            self._poke()

    # ---- message handling (pure state transitions, unit-tested) -------------------------------------------------
    def ingest_trade(self, symbol: str, price, size, ts, trade_id) -> bool:
        when = ts if isinstance(ts, datetime) else _ts(ts)
        if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0 or when is None:
            self.counters["malformed"] += 1
            return False
        cur = self.ticks.get(symbol)
        if cur is not None and not cur.cancelled:
            if trade_id is not None and trade_id == cur.trade_id:
                self.counters["duplicate"] += 1
                return False
            if when < cur.time:
                self.counters["out_of_order"] += 1
                return False
        self.seq += 1
        self.ticks[symbol] = Tick(symbol, float(price), size if isinstance(size, int) else None, when, trade_id,
                                  self.seq)  # fmt: skip
        return True

    def handle(self, msg: dict) -> None:
        kind, sym = msg.get("T"), msg.get("S")
        if kind == "t" and isinstance(sym, str):
            self.ingest_trade(sym, msg.get("p"), msg.get("s"), msg.get("t"), msg.get("i"))
        elif kind == "c" and isinstance(sym, str):  # correction of an earlier trade
            cur = self.ticks.get(sym)
            if cur is not None and cur.trade_id == msg.get("oi") and isinstance(msg.get("cp"), (int, float)):
                self.seq += 1
                cur.price, cur.trade_id, cur.seq = float(msg["cp"]), msg.get("ci", cur.trade_id), self.seq
        elif kind == "x" and isinstance(sym, str):  # cancel / error of an earlier trade
            cur = self.ticks.get(sym)
            if cur is not None and cur.trade_id == msg.get("i"):
                self.seq += 1
                cur.cancelled, cur.seq = True, self.seq
        elif kind == "error":
            self.counters["error"] += 1
            raise _StreamError(int(msg.get("code") or 0), str(msg.get("msg") or "error"))

    # ---- connection loop ----------------------------------------------------------------------------------------
    async def _open(self):
        if self._connect is not None:
            return await self._connect(self.url)
        from websockets.asyncio.client import connect

        return await connect(self.url, open_timeout=15, ping_interval=20, ping_timeout=20, max_size=2_000_000)

    async def _seed(self, symbols: list[str]) -> None:
        try:
            trades = await asyncio.to_thread(self.client.latest_trades, symbols)
        except Exception:  # noqa: BLE001 — seeding is best effort; the live feed still arrives
            log.info("stream seed failed")
            return
        for sym, t in trades.items():
            self.ingest_trade(sym, t.get("p"), t.get("s"), t.get("t"), t.get("i"))

    async def _sync_subscriptions(self, ws) -> None:
        want = {s for s in self.refs if us_symbol(s)}
        add, drop = sorted(want - self._subscribed), sorted(self._subscribed - want)
        if drop:
            await ws.send(json.dumps({"action": "unsubscribe", "trades": drop}))
        if add:
            await ws.send(json.dumps({"action": "subscribe", "trades": add}))
            await self._seed(add)
        self._subscribed = want

    async def _session(self) -> None:
        kid, sec = self.client.credentials()
        ws = await self._open()
        try:
            await ws.send(json.dumps({"action": "auth", "key": kid, "secret": sec}))
            authed = False
            deadline = time.monotonic() + 15
            while not authed:
                if time.monotonic() > deadline:
                    raise _StreamError(0, "authentication timed out")
                for m in _messages(await asyncio.wait_for(ws.recv(), timeout=15)):
                    if m.get("T") == "success" and m.get("msg") == "authenticated":
                        authed = True
                    else:
                        self.handle(m)
            self._subscribed = set()
            await self._sync_subscriptions(ws)
            self.connected_at = datetime.now(UTC)
            self.counters["live"] += 1
            self._set_status("live", None)
            idle_since: float | None = None
            while True:
                if not self.refs:
                    idle_since = idle_since or time.monotonic()
                    if time.monotonic() - idle_since > IDLE_CLOSE_SECONDS:
                        return
                else:
                    idle_since = None
                if self._wake is not None and self._wake.is_set():
                    self._wake.clear()
                    await self._sync_subscriptions(ws)
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except TimeoutError:
                    continue
                for m in _messages(raw):
                    self.handle(m)
        finally:
            self._subscribed = set()
            self.connected_at = None
            with contextlib.suppress(Exception):
                await ws.close()

    async def _run(self) -> None:
        delay = 1.0
        while self.refs:
            went_live = self.counters["live"]
            self._set_status("connecting" if not self.counters["reconnect"] else "reconnecting", None)
            try:
                await self._session()
                if not self.refs:
                    break
            except asyncio.CancelledError:
                raise
            except _StreamError as exc:
                fatal = exc.code in (401, 402, 403, 404, 409)  # auth / plan problems: retrying will not help soon
                if exc.code == 406:  # connection limit: another process holds the single free connection
                    self._set_status("error", "The live-data account allows one stream and it is in use elsewhere.")
                elif fatal:
                    self._set_status("error", f"The live-data service refused the stream ({exc.code}).")
                else:
                    self._set_status("reconnecting", f"Stream error ({exc.code or 'protocol'}).")
                delay = 60.0 if fatal or exc.code == 406 else delay
            except Exception as exc:  # noqa: BLE001 — network failures: back off and retry
                log.info("stream disconnected: %s", type(exc).__name__)
                self._set_status("reconnecting", "Disconnected from the feed; showing polled quotes.")
            if self.counters["live"] > went_live and delay < 60.0:
                delay = 1.0  # the last session worked: retry promptly
            self.counters["reconnect"] += 1
            await asyncio.sleep(delay * (0.75 + random.random() / 2))  # noqa: S311 (jitter, not crypto)
            delay = min(delay * 2, 60.0)
        self._set_status("idle", None)


class _StreamError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def _messages(raw) -> list[dict]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    items = data if isinstance(data, list) else [data]
    return [m for m in items if isinstance(m, dict)]

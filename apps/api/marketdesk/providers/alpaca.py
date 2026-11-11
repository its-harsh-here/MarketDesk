"""Alpaca Market Data client (free "Basic" plan): US option chains and IEX quotes (docs/DECISIONS.md #65).

* Option chains come from Alpaca's **indicative** options feed — a free, delayed derivative of OPRA, not OPRA itself
  — merged with open interest from the contracts list (which Alpaca dates; it is the prior session's figure).
* Stock trades come from the **IEX** feed: a single exchange, not consolidated (SIP) market data.

Only fixed Alpaca hosts are requested. The key pair travels in request headers and is never logged; errors are built
without URLs or headers. Read-only market-data endpoints only — the brokerage API is used solely for the public
contracts reference list, never for orders or account data.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from marketdesk.providers.base import OptionChain, OptionQuote, ProviderError

DATA = "https://data.alpaca.markets"
TRADING = "https://paper-api.alpaca.markets"  # contracts reference list (same data on paper and live)
STREAM_IEX = "wss://stream.data.alpaca.markets/v2/iex"
OPTIONS_SOURCE = "Indicative options feed (delayed; not the official OPRA feed)"
_SYM = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_KEY_ID = re.compile(r"^[A-Z0-9]{16,40}$")
_MAX_PAGES = 12


def us_symbol(symbol: str) -> str | None:
    """Alpaca symbol for a US listing, or None (Indian listings, indices, currencies and fixture names)."""
    s = (symbol or "").strip().upper()
    if not _SYM.match(s) or s.endswith((".NS", ".BO")) or "=" in s:
        return None
    return s.replace("-", ".")


def _dec(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _ts(v) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    s = v.rstrip("Z")
    if "." in s:  # Alpaca sends nanoseconds; Python parses up to microseconds
        head, frac = s.split(".", 1)
        s = f"{head}.{frac[:6]}"
    try:
        return datetime.fromisoformat(s).replace(tzinfo=UTC)
    except ValueError:
        return None


def normalize_chain(contracts: list[dict], snapshots: dict, expiry: date, spot: Decimal | None) -> OptionChain:
    """Pure: Alpaca contracts (reference + open interest) and snapshots (quotes) → one expiry of the chain."""
    expiries = sorted({d for c in contracts if (d := _date(c.get("expiration_date"))) is not None})
    bar_times = (_ts((s.get("dailyBar") or {}).get("t")) for s in snapshots.values() if isinstance(s, dict))
    session = max((t.date() for t in bar_times if t), default=None)
    calls: list[OptionQuote] = []
    puts: list[OptionQuote] = []
    for c in contracts:
        if _date(c.get("expiration_date")) != expiry:
            continue
        strike, side, sym = _dec(c.get("strike_price")), c.get("type"), c.get("symbol")
        if strike is None or side not in ("call", "put") or not isinstance(sym, str):
            continue
        snap = snapshots.get(sym) if isinstance(snapshots.get(sym), dict) else {}
        quote, trade, bar = snap.get("latestQuote") or {}, snap.get("latestTrade") or {}, snap.get("dailyBar") or {}
        bar_t = _ts(bar.get("t"))
        oi = c.get("open_interest")
        ask = _dec(quote.get("ap"))
        row = OptionQuote(
            contract=sym,
            strike=strike,
            last=_dec(trade.get("p")),
            bid=_dec(quote.get("bp")),
            ask=ask if ask else None,  # an ask of 0 means no offer
            # volume only from the latest session's daily bar; an older bar is not today's volume
            volume=int(bar["v"]) if bar_t and session and bar_t.date() == session and isinstance(bar.get("v"), int)
            else None,
            open_interest=int(oi) if isinstance(oi, str) and oi.isdigit() else None,
            implied_vol=_dec(snap.get("impliedVolatility")),
            in_the_money=None if spot is None else (strike < spot if side == "call" else strike > spot),
            last_trade=_ts(trade.get("t")),
        )  # fmt: skip
        (calls if side == "call" else puts).append(row)
    calls.sort(key=lambda o: o.strike)
    puts.sort(key=lambda o: o.strike)
    return OptionChain(expiries=expiries, expiry=expiry, calls=calls, puts=puts, currency="USD", source=OPTIONS_SOURCE)


def _date(v) -> date | None:
    try:
        return date.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


def oi_date(contracts: list[dict], expiry: date) -> str | None:
    dates = {c.get("open_interest_date") for c in contracts if _date(c.get("expiration_date")) == expiry}
    dates.discard(None)
    return max(dates) if dates else None


class AlpacaClient:
    def __init__(self, key_id: str | None, secret: str | None, timeout: float = 15.0, ttl: float = 120.0):
        kid, sec = (key_id or "").strip(), (secret or "").strip()
        if not kid or not sec:
            self.problem = "The live-data service is not configured on this server."
        elif not _KEY_ID.match(kid) or len(sec) < 20:
            self.problem = "The live-data service credentials are not valid."
        else:
            self.problem = None
        self._kid, self._sec = (kid, sec) if self.problem is None else (None, None)
        self.timeout = timeout
        self.ttl = ttl
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._kid is not None

    def credentials(self) -> tuple[str, str]:
        if not self.enabled:
            raise ProviderError("unsupported", self.problem or "The live-data service is not configured.")
        return self._kid, self._sec  # type: ignore[return-value]

    def _get(self, base: str, path: str, params: dict) -> dict:
        kid, sec = self.credentials()
        url = f"{base}{path}?{urllib.parse.urlencode(params)}"
        headers = {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec, "Accept": "application/json",
                   "User-Agent": "MarketDesk"}  # fmt: skip
        req = urllib.request.Request(url, headers=headers)  # noqa: S310 (fixed Alpaca hosts)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                data = json.loads(resp.read(20_000_000))
        except urllib.error.HTTPError as exc:
            kind = {429: "rate_limited", 404: "missing", 422: "missing", 401: "unsupported", 403: "unsupported"}.get(
                exc.code, "upstream_unavailable"
            )
            msg = "Live-data credentials rejected, or the plan lacks this feed." if exc.code in (401, 403) else (
                f"The live-data service request failed (HTTP {exc.code})."
            )  # fmt: skip
            raise ProviderError(kind, msg, retryable=exc.code >= 429) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise ProviderError("timeout", "The live-data service sent no valid data.", retryable=True) from None
        if not isinstance(data, dict):
            raise ProviderError("upstream_unavailable", "The live-data service returned an unexpected response.")
        return data

    def _cached(self, key: tuple, fn):
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = fn()
        with self._lock:
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = (time.monotonic(), value)
        return value

    def contracts(self, symbol: str) -> list[dict]:
        sym = us_symbol(symbol)
        if sym is None:
            raise ProviderError("unsupported", "Covers US listings only.")

        def load() -> list[dict]:
            today = datetime.now(UTC).date()
            params = {"underlying_symbols": sym, "status": "active", "limit": 10000,
                      "expiration_date_gte": today.isoformat(),
                      "expiration_date_lte": (today + timedelta(days=3 * 366)).isoformat()}  # fmt: skip
            out: list[dict] = []
            for _ in range(_MAX_PAGES):
                data = self._get(TRADING, "/v2/options/contracts", params)
                out += [c for c in data.get("option_contracts") or [] if isinstance(c, dict)]
                token = data.get("next_page_token")
                if not token:
                    break
                params["page_token"] = token
            return out

        return self._cached(("contracts", sym), load)

    def snapshots(self, symbol: str, expiry: date) -> dict:
        sym = us_symbol(symbol)
        if sym is None:
            raise ProviderError("unsupported", "Covers US listings only.")

        def load() -> dict:
            params = {"feed": "indicative", "limit": 1000, "expiration_date": expiry.isoformat()}
            out: dict = {}
            for _ in range(_MAX_PAGES):
                data = self._get(DATA, f"/v1beta1/options/snapshots/{sym}", params)
                snaps = data.get("snapshots") or {}
                if isinstance(snaps, dict):
                    out.update(snaps)
                token = data.get("next_page_token")
                if not token:
                    break
                params["page_token"] = token
            return out

        return self._cached(("snapshots", sym, expiry), load)

    def option_chain(self, symbol: str, expiry: date | None, spot: Decimal | None) -> tuple[OptionChain, str | None]:
        contracts = self.contracts(symbol)
        expiries = sorted({d for c in contracts if (d := _date(c.get("expiration_date"))) is not None})
        if not expiries:
            raise ProviderError("missing", f"No active option contracts are listed for {symbol}.")
        today = datetime.now(UTC).date()  # default: the first expiry after today (same-day contracts carry no IV)
        chosen = expiry if expiry in expiries else next((d for d in expiries if d > today), expiries[0])
        if expiry is not None and expiry not in expiries:
            raise ProviderError("missing", f"No {symbol} options expire on {expiry.isoformat()}.")
        chain = normalize_chain(contracts, self.snapshots(symbol, chosen), chosen, spot)
        return chain, oi_date(contracts, chosen)

    def latest_trades(self, symbols: list[str]) -> dict[str, dict]:
        """Latest IEX trade per symbol: {SYM: {"p": price, "s": size, "t": iso time, "i": id}} (REST seed)."""
        syms = [s for s in (us_symbol(x) for x in symbols) if s]
        if not syms:
            return {}
        data = self._get(DATA, "/v2/stocks/trades/latest", {"symbols": ",".join(syms), "feed": "iex"})
        trades = data.get("trades") or {}
        return {k: v for k, v in trades.items() if isinstance(v, dict)} if isinstance(trades, dict) else {}

    # ---- news (Benzinga via Alpaca) and the market screener ---------------------------------------------------------
    def news(self, symbol: str, limit: int = 30) -> list[dict]:
        """Headlines tagged with the symbol: {title, publisher, url, published_at, symbols}. No article bodies."""
        sym = us_symbol(symbol)
        if sym is None:
            raise ProviderError("unsupported", "Tagged news covers US listings only.")

        def load() -> list[dict]:
            data = self._get(DATA, "/v1beta1/news", {"symbols": sym, "limit": min(limit, 50), "sort": "desc"})
            out = []
            for n in data.get("news") or []:
                if not isinstance(n, dict) or not n.get("headline"):
                    continue
                url = n.get("url") if isinstance(n.get("url"), str) and n["url"].startswith("https://") else None
                src = str(n.get("source") or "").strip()
                out.append({
                    "title": str(n["headline"]).strip()[:300],
                    "publisher": src.capitalize() if src else None,
                    "url": url,
                    "published_at": _ts(n.get("created_at")),
                    "symbols": [s for s in n.get("symbols") or [] if isinstance(s, str)][:20],
                })  # fmt: skip
            return out

        return self._cached(("news", sym), load)

    def movers(self, top: int = 50) -> dict:
        """Market-wide top gainers and losers by percent change, as Alpaca's screener computes them."""
        return self._cached(("movers", top), lambda: self._get(DATA, "/v1beta1/screener/stocks/movers", {"top": top}))

    def most_actives(self, top: int = 50) -> dict:
        return self._cached(
            ("actives", top),
            lambda: self._get(DATA, "/v1beta1/screener/stocks/most-actives", {"by": "volume", "top": top}),
        )

    def snapshots_stock(self, symbols: list[str]) -> dict:
        """IEX snapshots (latest trade, daily bars) for up to 100 US symbols."""
        syms = sorted({s for s in (us_symbol(x) for x in symbols) if s})[:100]
        if not syms:
            return {}
        return self._cached(
            ("stock_snap", tuple(syms)),
            lambda: self._get(DATA, "/v2/stocks/snapshots", {"symbols": ",".join(syms), "feed": "iex"}),
        )

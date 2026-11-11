"""FixtureProvider: deterministic synthetic data committed to the repository.

Prices are fictitious and anchored to a fixed dataset date. A replay cursor can step
through a handful of extra sessions after the base date (for alert tests); timestamps
always remain the dataset's historical session times, never "now".
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from marketdesk.providers.base import (
    AnnualPeriod,
    AnnualStatements,
    CorporateAction,
    DailyBar,
    Fundamentals,
    HistoryRange,
    HolderRow,
    Holders,
    InstrumentRef,
    IntradayBar,
    IntradayHistory,
    IntradayRange,
    NewsItem,
    OptionChain,
    OptionQuote,
    PriceHistory,
    ProviderError,
    QuoteSnapshot,
)

FIXTURE_PREFIX = "SX:"
_SYMBOL_RE = re.compile(r"^SX:[A-Z0-9]{1,16}$")
RANGE_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60}


@dataclass(frozen=True)
class FixtureState:
    cursor_index: int = 0  # 0 = base date, n = n-th replay session
    fault: bool = False


@dataclass(frozen=True)
class FixtureDataset:
    meta: dict
    instruments: dict[str, dict]
    bars: dict[str, list[DailyBar]]
    base_date: date
    replay: list[date]
    benchmarks: list[str]
    starter_watchlist: list[str]
    statements: dict[str, list[dict]]

    def session_dates(self) -> list[date]:
        return [self.base_date, *self.replay]


@lru_cache(maxsize=4)
def load_dataset(fixtures_dir: str) -> FixtureDataset:
    root = Path(fixtures_dir) / "market"
    meta = json.loads((root / "instruments.json").read_text())
    instruments = {i["symbol"]: i for i in meta["instruments"]}
    bars: dict[str, list[DailyBar]] = {s: [] for s in instruments}
    with (root / "daily_bars.csv").open(newline="") as fh:
        for row in csv.DictReader(fh):
            bars[row["symbol"]].append(
                DailyBar(
                    session_date=date.fromisoformat(row["date"]),
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=int(row["volume"]) if row["volume"] else None,
                )
            )
    for series in bars.values():
        series.sort(key=lambda b: b.session_date)
    fin_path = root / "financials.json"
    statements = json.loads(fin_path.read_text())["statements"] if fin_path.exists() else {}
    ds = meta["dataset"]
    return FixtureDataset(
        meta=ds,
        instruments=instruments,
        bars=bars,
        base_date=date.fromisoformat(ds["base_date"]),
        replay=[date.fromisoformat(d) for d in ds["replay_sessions"]],
        benchmarks=meta["benchmarks"],
        starter_watchlist=meta["starter_watchlist"],
        statements=statements,
    )


def _bs(spot: float, strike: float, t: float, vol: float, r: float = 0.05) -> tuple[float, float]:
    """Black–Scholes call and put prices (for the fictitious sample chain only)."""
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    call = spot * n(d1) - strike * math.exp(-r * t) * n(d2)
    return call, call - spot + strike * math.exp(-r * t)


class FixtureProvider:
    name = "fixture"
    is_sample = True

    def __init__(self, fixtures_dir: Path, state_getter: Callable[[], FixtureState] | None = None):
        self.dataset = load_dataset(str(fixtures_dir))
        self._state_getter = state_getter or (lambda: FixtureState())

    # -- state -------------------------------------------------------------------
    def state(self) -> FixtureState:
        return self._state_getter()

    def cursor_date(self, state: FixtureState | None = None) -> date:
        state = state or self.state()
        dates = self.dataset.session_dates()
        idx = max(0, min(state.cursor_index, len(dates) - 1))
        return dates[idx]

    def cache_namespace(self) -> str:
        return f"c{self.state().cursor_index}"

    def simulating_outage(self) -> bool:
        return self.state().fault

    def _check_fault(self) -> None:
        if self.state().fault:
            raise ProviderError(
                "upstream_unavailable",
                "Simulated provider outage (fixture fault injection is enabled in Settings → Data).",
                retryable=True,
            )

    # -- helpers -----------------------------------------------------------------
    def validate_symbol(self, symbol: str) -> str:
        s = (symbol or "").strip().upper()
        if not s.startswith(FIXTURE_PREFIX) and _SYMBOL_RE.match(FIXTURE_PREFIX + s):
            s = FIXTURE_PREFIX + s
        if not _SYMBOL_RE.match(s) or s not in self.dataset.instruments:
            raise ProviderError(
                "unsupported",
                f"'{symbol}' is not in the sample dataset. Fixture mode only contains fictitious SX: instruments.",
            )
        return s

    def _ref(self, symbol: str) -> InstrumentRef:
        i = self.dataset.instruments[symbol]
        return InstrumentRef(symbol, i["name"], i["exchange"], i["currency"], i["timezone"], i["kind"])

    def _bars_to_cursor(self, symbol: str) -> list[DailyBar]:
        cursor = self.cursor_date()
        return [b for b in self.dataset.bars[symbol] if b.session_date <= cursor]

    def _market_time(self, symbol: str, session: date) -> datetime:
        inst = self.dataset.instruments[symbol]
        ct = inst.get("close_time") or {"hour": 15, "minute": 30}
        local = datetime.combine(session, time(ct["hour"], ct["minute"]), tzinfo=ZoneInfo(inst["timezone"]))
        return local.astimezone(UTC)

    def intraday(self, symbol: str, range_: IntradayRange) -> IntradayHistory:
        """Synthetic regular-session bars for the sample dataset's last session(s): a deterministic path from each
        daily bar's open to its close that stays inside its high/low. Fictitious, like every sample price."""
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        if range_ not in ("1D", "5D"):
            raise ProviderError("unsupported", f"Range {range_} is not supported.")
        daily = self._bars_to_cursor(symbol)
        sessions = daily[-1:] if range_ == "1D" else daily[-5:]
        if not sessions:
            raise ProviderError("missing", "No history in the sample dataset.")
        step, count = (5, 75) if range_ == "1D" else (15, 25)
        seed = sum(ord(c) for c in symbol)
        bars: list[IntradayBar] = []
        for d in sessions:
            start = self._market_time(symbol, d.session_date) - timedelta(minutes=step * count)
            o, c = float(d.open or d.close), float(d.close)
            hi, lo = float(d.high or max(o, c)), float(d.low or min(o, c))
            prev = o
            for i in range(count):
                f = (i + 1) / count
                wave = math.sin((i + seed) * 0.7) * 0.35 + math.sin((i * 3 + seed) * 0.23) * 0.25
                px = o + (c - o) * f + (hi - lo) * wave * (1 - abs(2 * f - 1))
                px = c if i == count - 1 else min(hi, max(lo, px))
                q = Decimal(str(round(px, 2)))
                bars.append(IntradayBar(start + timedelta(minutes=step * i), Decimal(str(round(prev, 2))),
                                        Decimal(str(round(max(prev, px), 2))), Decimal(str(round(min(prev, px), 2))), q,
                                        int((d.volume or 0) / count) or None))  # fmt: skip
                prev = px
        before = daily[-len(sessions) - 1].close if len(daily) > len(sessions) else None
        return IntradayHistory(self._ref(symbol), range_, f"{step}m", bars, before if range_ == "1D" else None)

    # -- interface ---------------------------------------------------------------
    def search(self, query: str, limit: int) -> list[InstrumentRef]:
        self._check_fault()
        q = (query or "").strip().upper()
        if not q:
            return []
        bare = q.removeprefix(FIXTURE_PREFIX)
        scored: list[tuple[int, str]] = []
        for sym, inst in self.dataset.instruments.items():
            short = sym.removeprefix(FIXTURE_PREFIX)
            name = inst["name"].upper()
            if short == bare:
                score = 0
            elif short.startswith(bare):
                score = 1
            elif name.startswith(bare) or any(w.startswith(bare) for w in name.split()):
                score = 2
            elif bare in name or bare in short:
                score = 3
            else:
                continue
            scored.append((score, sym))
        scored.sort()
        return [self._ref(sym) for _, sym in scored[:limit]]

    def quote(self, symbol: str) -> QuoteSnapshot:
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        inst = self.dataset.instruments[symbol]
        if inst.get("quote_status") == "missing":
            raise ProviderError("missing", inst.get("quote_note") or "No quotation available.")
        bars = self._bars_to_cursor(symbol)
        if not bars:
            raise ProviderError("missing", "No observations in the sample dataset up to the dataset date.")
        last = bars[-1]
        prev = bars[-2].close if len(bars) > 1 else None
        is_index = inst["kind"] == "INDEX"
        return QuoteSnapshot(
            instrument=self._ref(symbol),
            last_price=last.close,
            previous_close=prev,
            market_time=self._market_time(symbol, last.session_date),
            session_date=last.session_date,
            day_high=last.high,
            day_low=last.low,
            volume=None if is_index else last.volume,
            volume_note="Index volume is not reported." if is_index else "Completed sample session volume.",
            recent_bars=bars[-66:],
        )

    def history(self, symbol: str, range_: HistoryRange) -> PriceHistory:
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        if range_ not in RANGE_MONTHS:
            raise ProviderError("unsupported", f"Range {range_} is not supported.")
        bars = self._bars_to_cursor(symbol)
        if not bars:
            raise ProviderError("missing", "No history in the sample dataset.")
        start = bars[-1].session_date - relativedelta(months=RANGE_MONTHS[range_])
        return PriceHistory(
            instrument=self._ref(symbol),
            range=range_,
            bars=[b for b in bars if b.session_date > start],
            adjustment=self.dataset.meta["adjustment"],
        )

    def fundamentals(self, symbol: str) -> Fundamentals:
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        inst = self.dataset.instruments[symbol]
        bars = self._bars_to_cursor(symbol)
        ref = self._ref(symbol)
        notes = list(inst.get("coverage_notes") or [])
        if inst["kind"] == "INDEX" or not bars:
            return Fundamentals(ref, None, None, None, None, None, None, None, None, None, None, notes)
        price = bars[-1].close
        year = bars[-252:]
        cursor = bars[-1].session_date
        shares = inst.get("shares_outstanding")
        eps = inst.get("eps_ttm")
        bvps = inst.get("book_value_per_share")
        pe = None
        if eps is not None:
            if eps > 0:
                pe = (price / Decimal(str(eps))).quantize(Decimal("0.01"))
            else:
                notes.append("P/E is not meaningful because trailing earnings are negative.")
        divs = [
            Decimal(a["value"])
            for a in inst.get("corporate_actions", [])
            if a["kind"] == "DIVIDEND" and cursor - relativedelta(years=1) < date.fromisoformat(a["date"]) <= cursor
        ]
        dy = (sum(divs) / price * 100).quantize(Decimal("0.01")) if divs else None
        if not divs:
            notes.append("No dividends in the trailing twelve months of the sample dataset.")
        fiscal = inst.get("fiscal") or {}
        return Fundamentals(
            instrument=ref,
            market_cap=(price * Decimal(shares)).quantize(Decimal("1")) if shares else None,
            pe_ratio=pe,
            dividend_yield_percent=dy,
            fifty_two_week_high=max(b.high or b.close for b in year),
            fifty_two_week_low=min(b.low or b.close for b in year),
            price_to_book=(price / Decimal(str(bvps))).quantize(Decimal("0.01")) if bvps else None,
            sector=inst.get("sector"),
            industry=inst.get("industry"),
            last_fiscal_year_end=date.fromisoformat(fiscal["last_fiscal_year_end"]) if fiscal else None,
            most_recent_quarter=date.fromisoformat(fiscal["most_recent_quarter"]) if fiscal else None,
            notes=notes,
            summary=(
                f"{inst.get('name') or symbol} is a fictitious company in MarketDesk's sample dataset"
                + (f" ({inst['industry']}, {inst['sector']})." if inst.get("industry") and inst.get("sector") else ".")
                + " Its figures are synthetic and describe no real business."
            ),
        )

    def annual_statements(self, symbol: str) -> AnnualStatements:
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        cursor = self.cursor_date()

        def dec(v) -> Decimal | None:
            return None if v is None else Decimal(str(v))

        periods = [
            AnnualPeriod(date.fromisoformat(y["period_end"]), dec(y["revenue"]), dec(y["net_income"]),
                         dec(y["total_debt"]), dec(y["total_equity"]), dec(y.get("operating_cash_flow")),
                         dec(y.get("capex")), dec(y.get("cash")))
            for y in self.dataset.statements.get(symbol, [])
            if date.fromisoformat(y["period_end"]) <= cursor
        ]  # fmt: skip
        if not periods:
            raise ProviderError("missing", "The sample dataset has no annual statements for this instrument.")
        return AnnualStatements(self._ref(symbol), periods, "Sample annual statements (fictitious)", [])

    def holders(self, symbol: str) -> Holders:
        """Fictitious holders for the fictitious sample companies, derived deterministically from the symbol."""
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        seed = sum(ord(c) for c in symbol)
        cursor = self.cursor_date()
        reported = date(cursor.year, ((cursor.month - 1) // 3) * 3 + 1, 1) - relativedelta(days=1)
        names = ["Northwind Pension Trust", "Harbourline Mutual Fund", "Kestrel Insurance Co.", "Juniper Index Fund",
                 "Altamira Capital", "Bluefin Sovereign Fund"]  # fmt: skip
        rows = []
        for i, n in enumerate(names):
            pct = Decimal(30 + (seed * (i + 3)) % 40) / Decimal(1000) / (i + 1)
            shares = Decimal(1_000_000 * (6 - i) + seed * 100)
            change = Decimal((seed % 7) - 3) / Decimal(100)
            rows.append(HolderRow(f"{n} (fictitious)", shares, pct.quantize(Decimal("0.0001")), None, reported, change))
        insiders = Decimal(35 + seed % 30) / Decimal(100)
        inst = Decimal(15 + seed % 25) / Decimal(100)
        return Holders(insiders, inst, inst / (1 - insiders), 40 + seed % 60, rows[:4], rows[4:],
                       "Sample holders (fictitious)")  # fmt: skip

    def options(self, symbol: str, expiry: date | None) -> OptionChain:
        """A fictitious chain for the fictitious companies: Black–Scholes prices on the sample close with a volatility
        smile, deterministic open interest. Monthly expiries (third Friday) after the dataset date."""
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        cursor = self.cursor_date()
        spot = float(self.quote(symbol).last_price)
        expiries = []
        for months in range(0, 7):
            first = cursor.replace(day=1) + relativedelta(months=months)
            third_friday = first + relativedelta(days=(4 - first.weekday()) % 7 + 14)
            if third_friday > cursor:
                expiries.append(third_friday)
        expiries = expiries[:4]
        chosen = expiry if expiry in expiries else expiries[0]
        t = max((chosen - cursor).days, 1) / 365
        seed = sum(ord(c) for c in symbol)
        step = max(1.0, round(spot * 0.025))
        calls, puts = [], []
        for k in range(-8, 9):
            strike = round(spot / step) * step + k * step
            if strike <= 0:
                continue
            m = strike / spot
            iv = 0.28 + 0.6 * (m - 1) ** 2 + (seed % 5) / 100
            c, p = _bs(spot, strike, t, iv)
            oi_c = int(4000 * math.exp(-abs(k - 2) / 3) + seed % 97)
            oi_p = int(3500 * math.exp(-abs(k + 2) / 3) + seed % 89)
            for side, price, oi, itm, out in (
                ("C", c, oi_c, strike < spot, calls),
                ("P", p, oi_p, strike > spot, puts),
            ):
                q = Decimal(str(round(price, 2)))
                code = f"SX{symbol[3:]}{chosen:%y%m%d}{side}{int(strike * 1000):08d}"
                bid, ask = max(Decimal("0.01"), q - Decimal("0.05")), q + Decimal("0.05")
                iv_d = Decimal(str(round(iv, 4)))
                out.append(OptionQuote(code, Decimal(str(strike)), q, bid, ask, oi // 9, oi, iv_d, itm, None))
        return OptionChain(
            expiries, chosen, calls, puts, self._ref(symbol).currency, "Sample option chain (fictitious)"
        )

    def news(self, symbol: str) -> list[NewsItem]:
        """Sample headlines for the fictitious companies, written from the dataset's own dividends and annual
        statements (no links: there is no article behind them)."""
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        name = self.dataset.instruments[symbol].get("name") or symbol
        wire = "Sample wire (fictitious)"
        out = []
        for a in self.corporate_actions(symbol):
            verb = "declares" if a.kind == "DIVIDEND" else "announces"
            when = datetime.combine(a.action_date, time(4, 30), UTC)
            out.append(NewsItem(f"{name} {verb} {a.description.lower()}", wire, None, when, "press_release"))
        try:
            st = self.annual_statements(symbol)
            for p in st.periods[:3]:
                when = datetime.combine(p.period_end + relativedelta(days=45), time(11, 0), UTC)
                title = f"{name} reports results for the year ended {p.period_end:%d %b %Y}"
                out.append(NewsItem(title, wire, None, when, "news"))
        except ProviderError:
            pass
        cursor = datetime.combine(self.cursor_date(), time(23, 59), UTC)
        return sorted(
            (n for n in out if n.published_at and n.published_at <= cursor), key=lambda n: n.published_at, reverse=True
        )

    def corporate_actions(self, symbol: str) -> list[CorporateAction]:
        self._check_fault()
        symbol = self.validate_symbol(symbol)
        cursor = self.cursor_date()
        out = []
        for a in self.dataset.instruments[symbol].get("corporate_actions", []):
            d = date.fromisoformat(a["date"])
            if d <= cursor:
                out.append(CorporateAction(d, a["kind"], Decimal(a["value"]), a["description"]))
        return sorted(out, key=lambda a: a.action_date, reverse=True)

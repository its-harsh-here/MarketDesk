"""FixtureProvider: deterministic synthetic data committed to the repository.

Prices are fictitious and anchored to a fixed dataset date. A replay cursor can step
through a handful of extra sessions after the base date (for alert tests); timestamps
always remain the dataset's historical session times, never "now".
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from marketdesk.providers.base import (
    CorporateAction,
    DailyBar,
    Fundamentals,
    HistoryRange,
    InstrumentRef,
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
    ds = meta["dataset"]
    return FixtureDataset(
        meta=ds,
        instruments=instruments,
        bars=bars,
        base_date=date.fromisoformat(ds["base_date"]),
        replay=[date.fromisoformat(d) for d in ds["replay_sessions"]],
        benchmarks=meta["benchmarks"],
        starter_watchlist=meta["starter_watchlist"],
    )


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

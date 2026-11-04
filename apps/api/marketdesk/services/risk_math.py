"""Pure performance and risk arithmetic (M09). No I/O; every formula is stated here and in the API responses.

Conventions
- Daily valuation: cash + Σ quantity held at the end of the day × that day's as-traded close. Provider closes are
  split-adjusted, so the as-traded close is restored with the provider's own split history (close × product of the
  ratios of later splits); the ledger's recorded SPLIT entries change the quantity on their date. A close missing on a
  day (a holiday on one exchange) is carried forward for at most ``MAX_CARRY_DAYS`` calendar days; beyond that the day
  is left out as incomplete and its flows move to the next complete day.
- External flows: deposits (+) and withdrawals (−). For a single currency account, FX conversions are transfers in
  (+ amount received) or out (− amount converted); conversion fees are a cost of the paying account. In the
  consolidated view FX conversions are internal and not flows.
- Time-weighted return: daily r_t = (V_t − F_t) / V_{t−1} − 1, flows assumed at the end of their day; linked
  geometrically. Money-weighted return: the annual rate that sets the net present value of the flows and the final
  value to zero (XIRR, 365-day years).
- Annualized figures are given only for periods of at least 365 days; volatility only with at least 60 daily returns.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from marketdesk.services.ledger import LedgerEntry, TxnType, money, sort_entries

MAX_CARRY_DAYS = 10
MIN_VOL_RETURNS = 60
MIN_DAILY_PAIRS = 60
MIN_WEEKLY_PAIRS = 26
ZERO = Decimal(0)


# --------------------------------------------------------------------- price preparation
def as_traded(closes: Iterable[tuple[date, Decimal]], splits: Iterable[tuple[date, Decimal]]) -> dict[date, Decimal]:
    """Undo split adjustment: close(d) × Π ratio of splits dated after d (ratio = new shares per old share)."""
    sp = sorted((d, r) for d, r in splits if r and r > 0)
    out: dict[date, Decimal] = {}
    for d, c in closes:
        factor = Decimal(1)
        for sd, r in sp:
            if sd > d:
                factor *= r
        out[d] = c * factor
    return out


class CloseLookup:
    """Last close on or before a day, carried forward for at most MAX_CARRY_DAYS calendar days."""

    def __init__(self, closes: dict[date, Decimal]):
        self.days = sorted(closes)
        self.closes = closes

    def at(self, d: date) -> Decimal | None:
        lo, hi = 0, len(self.days)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.days[mid] <= d:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return None
        last = self.days[lo - 1]
        return self.closes[last] if (d - last).days <= MAX_CARRY_DAYS else None


# --------------------------------------------------------------------- valuation series
@dataclass
class Point:
    day: date
    value: Decimal
    flow: Decimal
    cash: Decimal


@dataclass
class Series:
    points: list[Point] = field(default_factory=list)
    skipped: list[tuple[date, str]] = field(default_factory=list)  # (day, reason) left out as incomplete
    flows: list[tuple[date, Decimal]] = field(default_factory=list)  # external flows, investor view: + into account


def flow_of(e: LedgerEntry, consolidated: bool) -> Decimal:
    if e.type == TxnType.DEPOSIT:
        return e.amount or ZERO
    if e.type == TxnType.WITHDRAWAL:
        return -(e.amount or ZERO)
    if consolidated:
        return ZERO
    if e.type == TxnType.FX_IN:
        return e.amount or ZERO
    if e.type == TxnType.FX_OUT:
        return -(e.amount or ZERO)
    return ZERO


def value_series(
    entries: list[LedgerEntry], prices: dict[str, CloseLookup], calendar: list[date], *, consolidated: bool = False
) -> Series:
    """Daily account values on `calendar` (ascending), from the first day on or after the first entry."""
    ordered = sort_entries(entries)
    out = Series()
    if not ordered:
        return out
    cash = ZERO
    qty: dict[str, Decimal] = {}
    i = 0
    pending = ZERO
    first = ordered[0].effective_date
    for day in calendar:
        if day < first:
            continue
        while i < len(ordered) and ordered[i].effective_date <= day:
            e = ordered[i]
            i += 1
            f = flow_of(e, consolidated)
            pending += f
            if f:
                out.flows.append((e.effective_date, f))
            if e.type in (TxnType.DEPOSIT, TxnType.FX_IN):
                cash += e.amount or ZERO
            elif e.type == TxnType.WITHDRAWAL:
                cash -= e.amount or ZERO
            elif e.type == TxnType.FX_OUT:
                cash -= (e.amount or ZERO) + e.fees
            elif e.type == TxnType.BUY:
                cash -= money(e.quantity * e.price) + e.fees  # type: ignore[operator]
                qty[e.symbol] = qty.get(e.symbol, ZERO) + e.quantity  # type: ignore[index, operator]
            elif e.type == TxnType.SELL:
                cash += money(e.quantity * e.price) - e.fees  # type: ignore[operator]
                qty[e.symbol] = qty.get(e.symbol, ZERO) - e.quantity  # type: ignore[index, operator]
            elif e.type == TxnType.DIVIDEND:
                cash += e.amount or ZERO
            elif e.type == TxnType.SPLIT:
                q = qty.get(e.symbol, ZERO)  # type: ignore[arg-type]
                qty[e.symbol] = q * e.split_to / e.split_from  # type: ignore[index, operator]
        value = cash
        missing = []
        for sym, q in qty.items():
            if q == 0:
                continue
            lk = prices.get(sym)
            c = lk.at(day) if lk else None
            if c is None:
                missing.append(sym)
            else:
                value += q * c
        if missing:
            out.skipped.append((day, f"no close within {MAX_CARRY_DAYS} days for {', '.join(sorted(missing))}"))
            continue
        out.points.append(Point(day, value, pending, cash))
        pending = ZERO
    return out


def combine(parts: list[tuple[Series, dict[date, Decimal] | None]]) -> Series:
    """Sum account series into one base currency, on days where every account has a value and every needed rate
    exists (None = already in base). Flows on left-out days move to the next kept day, converted at that day's rate."""
    out = Series()
    maps = []
    for s, _ in parts:
        out.skipped.extend(s.skipped)
        maps.append({p.day: p for p in s.points})
    days = sorted(set().union(*[set(m) for m in maps])) if maps else []
    pending = [ZERO for _ in parts]
    for day in days:
        for k, m in enumerate(maps):
            if day in m:
                pending[k] += m[day].flow
        rates = [Decimal(1) if fx is None else fx.get(day) for _, fx in parts]
        if not all(day in m for m in maps):
            continue
        if any(r is None for r in rates):
            out.skipped.append((day, "no USD/INR close within the carry window for this day"))
            continue
        value = sum((m[day].value * r for m, r in zip(maps, rates, strict=True)), ZERO)  # type: ignore[operator]
        cash = sum((m[day].cash * r for m, r in zip(maps, rates, strict=True)), ZERO)  # type: ignore[operator]
        flow = sum((f * r for f, r in zip(pending, rates, strict=True)), ZERO)  # type: ignore[operator]
        out.points.append(Point(day, value, flow, cash))
        pending = [ZERO for _ in parts]
    for s, fx in parts:
        for d, f in s.flows:
            r = Decimal(1) if fx is None else fx.get(d)
            if r is not None:
                out.flows.append((d, f * r))
    out.flows.sort()
    return out


# --------------------------------------------------------------------- returns
def twr_index(points: list[Point]) -> tuple[list[tuple[date, float]], list[tuple[date, float]]]:
    """(index rebased to 100 at the first point, daily returns). Days after a zero value restart the chain."""
    index: list[tuple[date, float]] = []
    rets: list[tuple[date, float]] = []
    level = 100.0
    prev: Point | None = None
    for p in points:
        if prev is not None and prev.value > 0:
            r = float((p.value - p.flow) / prev.value) - 1.0
            level *= 1.0 + r
            rets.append((p.day, r))
        index.append((p.day, level))
        prev = p
    return index, rets


def xirr(flows: list[tuple[date, Decimal]], end: date, end_value: Decimal) -> float | None:
    """Annual money-weighted return. `flows` are investor contributions (+ into the account); returns None when no
    rate solves the equation (for example, nothing invested)."""
    cfs = [(d, -float(a)) for d, a in flows if a] + [(end, float(end_value))]
    if not any(a < 0 for _, a in cfs) or not any(a > 0 for _, a in cfs):
        return None
    t0 = min(d for d, _ in cfs)

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** ((d - t0).days / 365.0) for d, a in cfs)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def annualize(total_return: float, days: int) -> float | None:
    if days < 365 or total_return <= -1:
        return None
    return (1.0 + total_return) ** (365.0 / days) - 1.0


def volatility(rets: list[float]) -> float | None:
    if len(rets) < MIN_VOL_RETURNS:
        return None
    m = sum(rets) / len(rets)
    return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(252)


def drawdowns(index: list[tuple[date, float]]) -> dict:
    """Underwater series and the maximum drawdown with its peak, trough and recovery dates."""
    peak_v, peak_d = -math.inf, None
    worst = {"depth": 0.0, "peak": None, "trough": None, "recovered": None}
    under: list[tuple[date, float]] = []
    current_peak_d = None
    for d, v in index:
        if v >= peak_v:
            peak_v, peak_d = v, d
            current_peak_d = d
        dd = v / peak_v - 1.0 if peak_v > 0 else 0.0
        under.append((d, dd))
        if dd < worst["depth"]:
            worst = {"depth": dd, "peak": current_peak_d, "trough": d, "recovered": None, "_peak_v": peak_v}
    if worst["trough"] is not None:
        after = [(d, v) for d, v in index if d > worst["trough"]]
        worst["recovered"] = next((d for d, v in after if v >= worst["_peak_v"]), None)
    worst.pop("_peak_v", None)
    return {"underwater": under, "max": worst, "current": under[-1][1] if under else None, "peak_day": peak_d}


def beta(port: list[tuple[date, float]], bench: list[tuple[date, float]]) -> tuple[float | None, float | None, int]:
    """(beta, correlation, n) on days where both have a return."""
    b = dict(bench)
    pairs = [(r, b[d]) for d, r in port if d in b]
    n = len(pairs)
    if n < MIN_DAILY_PAIRS:
        return None, None, n
    mp = sum(p for p, _ in pairs) / n
    mb = sum(q for _, q in pairs) / n
    cov = sum((p - mp) * (q - mb) for p, q in pairs) / (n - 1)
    vb = sum((q - mb) ** 2 for _, q in pairs) / (n - 1)
    vp = sum((p - mp) ** 2 for p, _ in pairs) / (n - 1)
    if vb == 0 or vp == 0:
        return None, None, n
    return cov / vb, cov / math.sqrt(vb * vp), n


# --------------------------------------------------------------------- correlation
def aligned_daily_returns(a: dict[date, Decimal], b: dict[date, Decimal]) -> list[tuple[float, float]]:
    """Returns between consecutive dates on which BOTH instruments closed (no carried-forward prices)."""
    common = sorted(set(a) & set(b))
    out = []
    for d0, d1 in zip(common, common[1:], strict=False):
        if a[d0] > 0 and b[d0] > 0:
            out.append((float(a[d1] / a[d0]) - 1.0, float(b[d1] / b[d0]) - 1.0))
    return out


def weekly_closes(closes: dict[date, Decimal]) -> dict[date, Decimal]:
    """Last close of each week, keyed by that week's Friday (for instruments on different exchanges/time zones)."""
    out: dict[date, tuple[date, Decimal]] = {}
    for d in sorted(closes):
        friday = d + timedelta(days=(4 - d.weekday()) % 7)
        out[friday] = (d, closes[d])
    return {k: v[1] for k, v in out.items()}


def pearson(pairs: list[tuple[float, float]]) -> float | None:
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx == 0 or syy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(sxx * syy)


def correlation(a: dict[date, Decimal], b: dict[date, Decimal], same_market: bool) -> dict:
    if same_market:
        pairs, method, need = aligned_daily_returns(a, b), "daily", MIN_DAILY_PAIRS
    else:
        pairs, method, need = aligned_daily_returns(weekly_closes(a), weekly_closes(b)), "weekly", MIN_WEEKLY_PAIRS
    if len(pairs) < need:
        return {
            "r": None,
            "n": len(pairs),
            "method": method,
            "why": f"Only {len(pairs)} aligned {method} returns; at least {need} are needed.",
        }
    r = pearson(pairs)
    return {
        "r": None if r is None else round(r, 2),
        "n": len(pairs),
        "method": method,
        "why": None if r is not None else "One of the series did not move.",
    }


# --------------------------------------------------------------------- rebalance
@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: Decimal
    price: Decimal | None


def rebalance(
    holdings: list[Holding],
    cash: Decimal,
    targets: dict[str, Decimal],
    *,
    extra_cash: Decimal = ZERO,
    whole_shares: bool = True,
    fee_pct: Decimal = ZERO,
) -> dict:
    """Trades that move each holding to its target weight of the account total (holdings + cash + extra cash).

    Target weights are percentages of the total; whatever the targets leave unallocated stays in cash. With whole
    shares, each trade is rounded toward zero to a whole number of shares at the last price. Fees are an assumed
    percentage of each trade's value, paid from cash. This is a simulation: nothing is submitted anywhere."""
    priced = [h for h in holdings if h.price is not None and h.price > 0]
    unpriced = [h.symbol for h in holdings if h not in priced and h.quantity]
    total = cash + extra_cash + sum((h.quantity * h.price for h in priced), ZERO)  # type: ignore[operator]
    rows = []
    cash_after = cash + extra_cash
    fees = ZERO
    for h in priced:
        value = h.quantity * h.price  # type: ignore[operator]
        tgt = targets.get(h.symbol, ZERO)
        target_value = total * tgt / 100
        trade_value = target_value - value
        shares = trade_value / h.price  # type: ignore[operator]
        if whole_shares:
            shares = shares.to_integral_value(rounding=ROUND_DOWN)
            trade_value = shares * h.price  # type: ignore[operator]
        fee = abs(trade_value) * fee_pct / 100
        fees += fee
        cash_after -= trade_value + fee
        new_value = value + trade_value
        rows.append(
            {
                "symbol": h.symbol,
                "price": h.price,
                "quantity": h.quantity,
                "value": value,
                "target_pct": tgt,
                "target_value": target_value,
                "trade_shares": shares,
                "trade_value": trade_value,
                "fee": fee,
                "new_quantity": h.quantity + shares,
                "new_value": new_value,
            }
        )
    for r in rows:
        r["weight_pct"] = r["value"] / total * 100 if total else None
        r["new_weight_pct"] = r["new_value"] / total * 100 if total else None
    missing_targets = sorted(s for s in targets if s not in {h.symbol for h in priced})
    return {
        "total": total,
        "cash_before": cash,
        "extra_cash": extra_cash,
        "cash_after": cash_after,
        "cash_weight_after_pct": cash_after / total * 100 if total else None,
        "fees": fees,
        "rows": rows,
        "unpriced": unpriced,
        "targets_without_holding": missing_targets,
        "target_sum_pct": sum(targets.values(), ZERO),
        "warnings": (["Cash after these trades would be negative: reduce buys or add cash."] if cash_after < 0 else []),
    }

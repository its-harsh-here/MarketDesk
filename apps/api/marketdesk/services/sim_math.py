"""Research simulation arithmetic (M13): long-only rule tests and a paper portfolio. Pure functions; no I/O.

Execution model (both): a decision made with information up to a session's close is executed at the NEXT session's
open, never at the close that produced the signal. Fill price = open × (1 + slippage) for buys, × (1 − slippage) for
sells; a fee (percent of the traded value) is paid from cash. Whole shares only; no leverage, no shorting.

Prices: the provider's daily bars are split-adjusted (open/high/low/close on one basis), so the rule test trades in
adjusted shares and a split needs no extra step. Dividends are credited in cash when a position is held at the close
before the ex-date: the provider's as-traded dividend per share is converted to the adjusted basis (÷ the product of
later split ratios). Interest on cash is not modelled.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal

ZERO = Decimal(0)
RULES = ("buy_and_hold", "sma_cross", "momentum")


@dataclass(frozen=True)
class Bar:
    day: date
    open: Decimal
    close: Decimal


@dataclass(frozen=True)
class Costs:
    fee_pct: Decimal = ZERO  # percent of traded value
    slippage_bps: Decimal = ZERO  # basis points against the trader

    def buy_price(self, open_: Decimal) -> Decimal:
        return open_ * (1 + self.slippage_bps / Decimal(10_000))

    def sell_price(self, open_: Decimal) -> Decimal:
        return open_ * (1 - self.slippage_bps / Decimal(10_000))

    def fee(self, value: Decimal) -> Decimal:
        return abs(value) * self.fee_pct / 100


def data_hash(bars: list[Bar], dividends: dict[date, Decimal]) -> str:
    """Fingerprint of exactly the data a run used, so a re-run can prove it saw the same inputs."""
    h = hashlib.sha256()
    for b in bars:
        h.update(f"{b.day.isoformat()},{b.open},{b.close};".encode())
    for d in sorted(dividends):
        h.update(f"div:{d.isoformat()},{dividends[d]};".encode())
    return h.hexdigest()


def adjusted_dividends(divs: list[tuple[date, Decimal]], splits: list[tuple[date, Decimal]]) -> dict[date, Decimal]:
    out: dict[date, Decimal] = {}
    for d, amount in divs:
        factor = Decimal(1)
        for sd, r in splits:
            if sd > d and r > 0:
                factor *= r
        out[d] = out.get(d, ZERO) + amount / factor
    return out


def signals(rule: str, closes: list[Decimal], params: dict) -> list[bool]:
    """Desired position (True = long) decided at each close, using closes up to and including that day only."""
    n = len(closes)
    if rule == "buy_and_hold":
        return [True] * n
    if rule == "sma_cross":
        fast, slow = int(params["fast"]), int(params["slow"])
        out = []
        for i in range(n):
            if i + 1 < slow:
                out.append(False)
                continue
            f = sum(closes[i + 1 - fast : i + 1]) / fast
            s = sum(closes[i + 1 - slow : i + 1]) / slow
            out.append(f > s)
        return out
    if rule == "momentum":
        lb = int(params["lookback"])
        return [i >= lb and closes[i] > closes[i - lb] for i in range(n)]
    raise ValueError(f"Unknown rule {rule}")


def validate_params(rule: str, params: dict) -> dict:
    if rule not in RULES:
        raise ValueError("Choose buy and hold, moving-average cross or momentum.")
    if rule == "sma_cross":
        fast, slow = int(params.get("fast", 20)), int(params.get("slow", 50))
        if not 2 <= fast < slow <= 250:
            raise ValueError("Moving averages need 2 ≤ fast < slow ≤ 250 sessions.")
        return {"fast": fast, "slow": slow}
    if rule == "momentum":
        lb = int(params.get("lookback", 60))
        if not 5 <= lb <= 250:
            raise ValueError("Momentum look-back must be 5 to 250 sessions.")
        return {"lookback": lb}
    return {}


def run_rule(
    bars: list[Bar], rule: str, params: dict, costs: Costs, cash0: Decimal, dividends: dict[date, Decimal] | None = None
) -> dict:
    """Daily simulation. The decision at close i is executed at the open of i + 1."""
    dividends = dividends or {}
    want = signals(rule, [b.close for b in bars], params)
    cash, shares = cash0, ZERO
    trades, equity = [], []
    held_days = 0
    for i, b in enumerate(bars):
        if i > 0:
            if shares > 0 and b.day in dividends:  # held at the previous close → entitled
                cash += shares * dividends[b.day]
            target = want[i - 1]
            if target and shares == 0:
                px = costs.buy_price(b.open)
                qty = (cash / (px * (1 + costs.fee_pct / 100))).to_integral_value(rounding=ROUND_DOWN)
                if qty > 0:
                    value = qty * px
                    fee = costs.fee(value)
                    cash -= value + fee
                    shares = qty
                    trades.append(
                        {
                            "day": b.day.isoformat(),
                            "side": "BUY",
                            "qty": qty,
                            "price": px,
                            "fee": fee,
                            "signal_day": bars[i - 1].day.isoformat(),
                        }
                    )
            elif not target and shares > 0:
                px = costs.sell_price(b.open)
                value = shares * px
                fee = costs.fee(value)
                cash += value - fee
                trades.append(
                    {
                        "day": b.day.isoformat(),
                        "side": "SELL",
                        "qty": shares,
                        "price": px,
                        "fee": fee,
                        "signal_day": bars[i - 1].day.isoformat(),
                    }
                )
                shares = ZERO
        held_days += int(shares > 0)
        equity.append((b.day, cash + shares * b.close))
    return {
        "equity": equity,
        "trades": trades,
        "final_cash": cash,
        "final_shares": shares,
        "exposure_pct": held_days / len(bars) * 100 if bars else 0.0,
    }


def summarize(equity: list[tuple[date, Decimal]], start_value: Decimal) -> dict:
    if not equity:
        return {}
    end = equity[-1][1]
    days = (equity[-1][0] - equity[0][0]).days
    total = float(end / start_value) - 1
    vals = [float(v) for _, v in equity]
    rets = [b / a - 1 for a, b in zip(vals, vals[1:], strict=False) if a > 0]
    peak, mdd = -math.inf, 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1 if peak > 0 else 0.0)
    vol = None
    if len(rets) >= 60:
        m = sum(rets) / len(rets)
        vol = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(252)
    return {
        "start": equity[0][0].isoformat(),
        "end": equity[-1][0].isoformat(),
        "days": days,
        "end_value": end,
        "total_return_pct": total * 100,
        "cagr_pct": ((1 + total) ** (365 / days) - 1) * 100 if days >= 365 and total > -1 else None,
        "max_drawdown_pct": mdd * 100,
        "volatility_pct": None if vol is None else vol * 100,
    }


# --------------------------------------------------------------------- paper engine
@dataclass(frozen=True)
class Order:
    id: int
    side: str  # BUY | SELL
    symbol: str
    quantity: Decimal
    placed_session: date  # the latest session whose close was known when the order was placed


def fill_orders(orders: list[Order], bars_by_symbol: dict[str, list[Bar]], costs: Costs, cash0: Decimal) -> dict:
    """Replay paper orders in placement order: each fills at the open of the first session after `placed_session`,
    if one exists yet; a buy needs the cash and a sell the shares at that moment, else it is rejected with a reason.
    Uses the same adjusted price basis for every symbol."""
    cash = cash0
    pos: dict[str, Decimal] = {}
    cost: dict[str, Decimal] = {}
    results = {}
    for o in sorted(orders, key=lambda x: (x.placed_session, x.id)):
        bars = bars_by_symbol.get(o.symbol) or []
        nxt = next((b for b in bars if b.day > o.placed_session), None)
        if nxt is None:
            results[o.id] = {"status": "pending", "reason": "Waiting for the next session's opening price."}
            continue
        if o.side == "BUY":
            px = costs.buy_price(nxt.open)
            value = o.quantity * px
            fee = costs.fee(value)
            if value + fee > cash:
                results[o.id] = {"status": "rejected", "reason": f"Not enough simulated cash at the fill ({cash:.2f})."}
                continue
            cash -= value + fee
            pos[o.symbol] = pos.get(o.symbol, ZERO) + o.quantity
            cost[o.symbol] = cost.get(o.symbol, ZERO) + value + fee
        else:
            held = pos.get(o.symbol, ZERO)
            if o.quantity > held:
                results[o.id] = {"status": "rejected", "reason": f"Only {held} simulated shares held at the fill."}
                continue
            px = costs.sell_price(nxt.open)
            value = o.quantity * px
            fee = costs.fee(value)
            cash += value - fee
            cost[o.symbol] = cost[o.symbol] * (held - o.quantity) / held if held else ZERO
            pos[o.symbol] = held - o.quantity
        results[o.id] = {"status": "filled", "fill_day": nxt.day.isoformat(), "fill_price": px, "fee": fee}
    return {"cash": cash, "positions": {s: q for s, q in pos.items() if q > 0}, "cost": cost, "orders": results}

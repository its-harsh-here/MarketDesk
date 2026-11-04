"""Deterministic valuation arithmetic (M11). Every output is hypothetical: it follows from the inputs, not from data.

DCF (equity, two stages)
    Cash flow definition: free cash flow to equity, approximated as operating cash flow − capital expenditure (as
    reported, after interest and tax). The approximation assumes no net new borrowing; it is discounted at a cost of
    equity, so no debt is subtracted afterwards.
    Year t = 1..N: FCF_t = FCF_0 × (1 + g)^t;  PV_t = FCF_t ÷ (1 + r)^t
    Terminal value at N (Gordon growth): TV = FCF_N × (1 + g_T) ÷ (r − g_T);  PV_TV = TV ÷ (1 + r)^N
    Equity value = Σ PV_t + PV_TV;  value per share = equity value ÷ shares outstanding.
    Rejected: r ≤ g_T (the terminal formula has no finite value), r outside 1–40%, g outside −50–100%, g_T outside
    −5–10% or within 0.5 percentage points of r, N outside 1–15, FCF_0 ≤ 0, shares ≤ 0.

Peer multiples
    Implied price = peer multiple × the company's own per-share figure (EPS = price ÷ own P/E; book value per share =
    price ÷ own P/B), at the minimum, quartiles, median and maximum of the peers' multiples.

Portfolio stress
    New value = Σ holdings × (1 + equity shock of the holding's market or its own shock) × (1 + FX shock for non-base
    currencies) + cash × (1 + FX shock for non-base cash); a deterministic what-if, not a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


class ValuationError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class DcfInputs:
    fcf0: Decimal  # base-year free cash flow, in the reporting currency
    years: int
    growth_pct: Decimal  # stage-1 annual growth of FCF
    terminal_growth_pct: Decimal
    discount_pct: Decimal  # cost of equity
    shares: Decimal

    @classmethod
    def parse(cls, raw: dict) -> DcfInputs:
        def dec(name: str) -> Decimal:
            try:
                v = Decimal(str(raw.get(name)).strip().replace(",", ""))
            except (InvalidOperation, ValueError) as err:
                raise ValuationError(name, f"{LABELS[name]} must be a plain number.") from err
            if not v.is_finite():
                raise ValuationError(name, f"{LABELS[name]} must be a finite number.")
            return v

        try:
            years = int(str(raw.get("years")))
        except ValueError as err:
            raise ValuationError("years", "Years of explicit forecast must be a whole number.") from err
        out = cls(dec("fcf0"), years, dec("growth_pct"), dec("terminal_growth_pct"), dec("discount_pct"), dec("shares"))
        out.validate()
        return out

    def validate(self) -> None:
        if self.fcf0 <= 0:
            raise ValuationError(
                "fcf0",
                "Base free cash flow must be positive: discounting negative cash flows does not "
                "give a meaningful value. Enter a normalized, positive figure if you expect one.",
            )
        if not 1 <= self.years <= 15:
            raise ValuationError("years", "Use 1 to 15 years of explicit forecast.")
        if not Decimal(1) <= self.discount_pct <= Decimal(40):
            raise ValuationError("discount_pct", "The discount rate must be between 1% and 40%.")
        if not Decimal(-50) <= self.growth_pct <= Decimal(100):
            raise ValuationError("growth_pct", "Forecast growth must be between −50% and 100% a year.")
        if not Decimal(-5) <= self.terminal_growth_pct <= Decimal(10):
            raise ValuationError("terminal_growth_pct", "Terminal growth must be between −5% and 10% a year.")
        if self.terminal_growth_pct >= self.discount_pct - Decimal("0.5"):
            raise ValuationError(
                "terminal_growth_pct",
                "Terminal growth must be at least 0.5 percentage points below "
                "the discount rate; otherwise the terminal value is infinite or meaningless.",
            )
        if self.shares <= 0:
            raise ValuationError("shares", "Shares outstanding must be positive.")


LABELS = {
    "fcf0": "Base free cash flow",
    "years": "Years of explicit forecast",
    "growth_pct": "Forecast growth",
    "terminal_growth_pct": "Terminal growth",
    "discount_pct": "Discount rate (cost of equity)",
    "shares": "Shares outstanding",
}


def dcf(inp: DcfInputs) -> dict:
    r = inp.discount_pct / HUNDRED
    g = inp.growth_pct / HUNDRED
    gt = inp.terminal_growth_pct / HUNDRED
    rows = []
    fcf = inp.fcf0
    pv_sum = ZERO
    for t in range(1, inp.years + 1):
        fcf = fcf * (ONE + g)
        df = ONE / (ONE + r) ** t
        pv = fcf * df
        pv_sum += pv
        rows.append({"year": t, "fcf": fcf, "discount_factor": df, "pv": pv})
    tv = fcf * (ONE + gt) / (r - gt)
    pv_tv = tv / (ONE + r) ** inp.years
    equity = pv_sum + pv_tv
    return {
        "rows": rows,
        "pv_forecast": pv_sum,
        "terminal_value": tv,
        "pv_terminal": pv_tv,
        "equity_value": equity,
        "per_share": equity / inp.shares,
        "terminal_share_pct": pv_tv / equity * HUNDRED,
    }


AXES = {
    "discount_pct": (Decimal(1), "pp"),
    "terminal_growth_pct": (Decimal("0.5"), "pp"),
    "growth_pct": (Decimal(2), "pp"),
}


def sensitivity(inp: DcfInputs, rows_axis: str, cols_axis: str, steps: int = 2) -> dict:
    """Value per share on a (2·steps+1)² grid around the inputs; invalid combinations are None with the reason."""
    if rows_axis not in AXES or cols_axis not in AXES or rows_axis == cols_axis:
        raise ValuationError("axes", "Choose two different assumptions for the sensitivity table.")

    def values(axis: str) -> list[Decimal]:
        step = AXES[axis][0]
        base = getattr(inp, axis)
        return [base + step * k for k in range(-steps, steps + 1)]

    rv, cv = values(rows_axis), values(cols_axis)
    grid = []
    for a in rv:
        row = []
        for b in cv:
            try:
                trial = DcfInputs(**{**inp.__dict__, rows_axis: a, cols_axis: b})
                trial.validate()
                row.append({"value": dcf(trial)["per_share"], "why": None})
            except ValuationError as err:
                row.append({"value": None, "why": err.message})
        grid.append(row)
    return {"rows_axis": rows_axis, "cols_axis": cols_axis, "rows": rv, "cols": cv, "grid": grid}


def quantiles(values: list[Decimal]) -> dict:
    v = sorted(values)
    n = len(v)

    def q(p: Decimal) -> Decimal:  # linear interpolation between closest ranks
        pos = (n - 1) * p
        lo = int(pos)
        frac = pos - lo
        return v[lo] if lo + 1 >= n else v[lo] + (v[lo + 1] - v[lo]) * frac

    return {
        "min": v[0],
        "p25": q(Decimal("0.25")),
        "median": q(Decimal("0.5")),
        "p75": q(Decimal("0.75")),
        "max": v[-1],
    }


def multiple_range(peer_multiples: list[Decimal], own_per_share: Decimal | None, min_peers: int = 2) -> dict:
    vals = [m for m in peer_multiples if m is not None and m > 0]
    if own_per_share is None or own_per_share <= 0:
        return {
            "available": False,
            "why": "The company's own figure is missing or not positive, so a multiple does not "
            "apply (for P/E: loss-making).",
        }
    if len(vals) < min_peers:
        return {
            "available": False,
            "why": f"{len(vals)} peer(s) with a positive multiple; at least {min_peers} are needed.",
        }
    qs = quantiles(vals)
    return {
        "available": True,
        "n": len(vals),
        "multiples": qs,
        "implied": {k: v * own_per_share for k, v in qs.items()},
    }


@dataclass(frozen=True)
class StressHolding:
    symbol: str
    currency: str
    market: str  # e.g. "IN", "US"
    value: Decimal  # in its own currency


def stress(
    holdings: list[StressHolding],
    cash: dict[str, Decimal],
    rates_to_base: dict[str, Decimal],
    base: str,
    market_shocks_pct: dict[str, Decimal],
    symbol_shocks_pct: dict[str, Decimal],
    fx_shocks_pct: dict[str, Decimal],
) -> dict:
    for name, shocks in (("market", market_shocks_pct), ("symbol", symbol_shocks_pct), ("fx", fx_shocks_pct)):
        for k, v in shocks.items():
            if not Decimal(-100) <= v <= Decimal(300):
                raise ValuationError(name, f"Shock for {k} must be between −100% and +300%.")
    rows = []
    before_total = after_total = ZERO
    for h in holdings:
        rate = rates_to_base.get(h.currency)
        if rate is None:
            raise ValuationError("fx", f"No {h.currency}/{base} rate to express {h.symbol} in {base}.")
        price_shock = symbol_shocks_pct.get(h.symbol, market_shocks_pct.get(h.market, ZERO))
        fx_shock = fx_shocks_pct.get(h.currency, ZERO) if h.currency != base else ZERO
        before = h.value * rate
        after = h.value * (ONE + price_shock / HUNDRED) * rate * (ONE + fx_shock / HUNDRED)
        before_total += before
        after_total += after
        rows.append(
            {
                "symbol": h.symbol,
                "currency": h.currency,
                "market": h.market,
                "price_shock_pct": price_shock,
                "fx_shock_pct": fx_shock,
                "before": before,
                "after": after,
                "change": after - before,
            }
        )
    cash_rows = []
    for ccy, amount in cash.items():
        rate = rates_to_base.get(ccy)
        if rate is None or amount == 0:
            continue
        fx_shock = fx_shocks_pct.get(ccy, ZERO) if ccy != base else ZERO
        before = amount * rate
        after = before * (ONE + fx_shock / HUNDRED)
        before_total += before
        after_total += after
        cash_rows.append(
            {"currency": ccy, "fx_shock_pct": fx_shock, "before": before, "after": after, "change": after - before}
        )
    change = after_total - before_total
    return {
        "base": base,
        "before": before_total,
        "after": after_total,
        "change": change,
        "change_pct": change / before_total * HUNDRED if before_total else None,
        "rows": sorted(rows, key=lambda r: r["change"]),
        "cash": cash_rows,
    }

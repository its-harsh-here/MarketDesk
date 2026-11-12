"""Financial analysis (terminal roadmap T2). Pure functions over normalized statements; no I/O.

Input statements have the shape produced by ``financials.normalize_statements``: ``period`` ("annual" | "quarterly"),
``period_ends`` (newest first) and ``lines`` (each with ``values``: value, unit, start, end, form, filed, accession).
Every derived figure states its formula; a figure that cannot be computed says why (never zero-filled).

Conventions (also shown in the UI):
- Ratios use values of the same period; balance-sheet items are period-end (ending, not average) values.
- Per-share figures divide by the diluted weighted-average shares of the same period.
- Growth compares a period with the one ending about a year earlier; CAGR needs positive start and end values.
- ROIC = operating income × (1 − effective tax rate) ÷ (equity + long-term debt + current debt − cash). The tax rate
  is income tax ÷ income before tax, used only between 0% and 50%; otherwise ROIC is not shown.
- Valuation bands use daily split-adjusted closes and, for each day, the latest annual figures already filed by then
  (point in time by filing date), converted to today's share basis with the provider's split history.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal(0)
PCT = Decimal(100)


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def series(st: dict, key: str) -> dict[date, dict]:
    for line in st.get("lines") or []:
        if line["key"] == key:
            return {_d(v["end"]): v for v in line.get("values") or []}
    return {}


def _num(s: dict[date, dict], end: date) -> Decimal | None:
    v = s.get(end)
    return None if v is None else Decimal(str(v["value"]))


def _div(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _row(key: str, label: str, unit: str, formula: str, values: list, whys: list | None = None) -> dict:
    return {"key": key, "label": label, "unit": unit, "formula": formula, "values": values, "why": whys}


def _ends(st: dict) -> list[date]:
    return [_d(e) for e in st.get("period_ends") or []]


def _fcf(st: dict) -> dict[date, Decimal]:
    ocf, capex = series(st, "operating_cash_flow"), series(st, "capex")
    out = {}
    for end in ocf:
        o, c = _num(ocf, end), _num(capex, end)
        if o is not None and c is not None:
            out[end] = o - c
    return out


# --------------------------------------------------------------------- tables
def per_share(st: dict) -> dict:
    ends = _ends(st)
    sh = series(st, "shares_diluted")
    rev, eq, eps = series(st, "revenue"), series(st, "equity"), series(st, "eps_diluted")
    fcf = _fcf(st)
    missing = "No diluted weighted-average share count for this period."

    def per(values: dict, unit_from):
        vals, whys = [], []
        for e in ends:
            s = _num(sh, e)
            x = values.get(e) if isinstance(values.get(e), Decimal) else _num(values, e)
            q = _div(x, s)
            vals.append(q)
            whys.append(None if q is not None else (missing if s is None else "Input not reported."))
        return vals, whys

    rows = []
    v, w = [_num(eps, e) for e in ends], None
    rows.append(_row("eps", "Diluted EPS (reported)", "per_share", "As reported in the filing", v, w))
    for key, label, src, formula in (
        ("revenue_ps", "Revenue per share", rev, "Revenue ÷ diluted weighted-average shares"),
        ("fcf_ps", "Free cash flow per share", fcf, "(Operating cash flow − capex) ÷ diluted weighted-average shares"),
        ("book_ps", "Book value per share", eq, "Period-end equity ÷ diluted weighted-average shares"),
    ):
        vals, whys = per(src, None)
        rows.append(_row(key, label, "per_share", formula, vals, whys))
    return {"columns": ends, "rows": rows}


COMMON_SIZE = (
    (
        "income",
        "revenue",
        ("cost_of_revenue", "gross_profit", "operating_income", "pretax_income", "income_tax", "net_income"),
    ),
    ("balance", "total_assets", ("cash", "total_liabilities", "long_term_debt", "current_debt", "equity")),
    ("cashflow", "revenue", ("operating_cash_flow", "capex", "depreciation")),
)
LABELS = {
    "cost_of_revenue": "Cost of revenue",
    "gross_profit": "Gross profit",
    "operating_income": "Operating income",
    "pretax_income": "Income before tax",
    "income_tax": "Income tax",
    "net_income": "Net income",
    "cash": "Cash and equivalents",
    "total_liabilities": "Total liabilities",
    "long_term_debt": "Long-term debt",
    "current_debt": "Current debt",
    "equity": "Shareholders' equity",
    "operating_cash_flow": "Operating cash flow",
    "capex": "Capital expenditure",
    "depreciation": "Depreciation and amortization",
    "revenue": "Revenue",
    "total_assets": "Total assets",
}


def common_size(st: dict) -> dict:
    ends = _ends(st)
    rows = []
    for statement, base_key, keys in COMMON_SIZE:
        base = series(st, base_key)
        for k in keys:
            s = series(st, k)
            if not s:
                continue
            vals, whys = [], []
            for e in ends:
                b, x = _num(base, e), _num(s, e)
                q = _div(x, b)
                vals.append(None if q is None else q * PCT)
                whys.append(None if q is not None else ("No " + LABELS[base_key].lower() + "." if b is None else None))
            rows.append(
                {
                    **_row(
                        f"cs_{k}", LABELS[k], "percent", f"{LABELS[k]} ÷ {LABELS[base_key].lower()} × 100", vals, whys
                    ),
                    "statement": statement,
                }
            )
    return {"columns": ends, "rows": rows}


def margins(st: dict) -> dict:
    ends = _ends(st)
    rev = series(st, "revenue")
    fcf = _fcf(st)
    op, dep = series(st, "operating_income"), series(st, "depreciation")
    rows = []
    for key, label, num, formula in (
        ("gross_margin", "Gross margin", series(st, "gross_profit"), "Gross profit ÷ revenue"),
        ("operating_margin", "Operating margin", op, "Operating income ÷ revenue"),
        ("ebitda_margin", "EBITDA margin", None, "(Operating income + depreciation and amortization) ÷ revenue"),
        ("net_margin", "Net margin", series(st, "net_income"), "Net income ÷ revenue"),
        ("fcf_margin", "Free-cash-flow margin", None, "(Operating cash flow − capex) ÷ revenue"),
    ):
        vals = []
        for e in ends:
            r = _num(rev, e)
            if key == "ebitda_margin":
                o, d = _num(op, e), _num(dep, e)
                x = o + d if o is not None and d is not None else None
            elif key == "fcf_margin":
                x = fcf.get(e)
            else:
                x = _num(num, e)
            q = _div(x, r)
            vals.append(None if q is None else q * PCT)
        rows.append(_row(key, label, "percent", formula + " × 100", vals))
    return {"columns": ends, "rows": rows}


def _year_before(ends: list[date], e: date, years: int = 1) -> date | None:
    target = e - timedelta(days=365 * years)
    best = min(ends, key=lambda x: abs((x - target).days), default=None)
    return best if best is not None and abs((best - target).days) <= 45 else None


GROWTH_KEYS = (
    ("revenue", "Revenue"),
    ("operating_income", "Operating income"),
    ("net_income", "Net income"),
    ("eps_diluted", "Diluted EPS"),
    ("fcf", "Free cash flow"),
    ("equity", "Book value (equity)"),
)


def _growth_series(st: dict, key: str) -> dict[date, Decimal]:
    if key == "fcf":
        return _fcf(st)
    return {e: Decimal(str(v["value"])) for e, v in series(st, key).items()}


def growth(st: dict) -> dict:
    """Year-on-year growth (for quarters: against the same quarter a year earlier). Undefined when the earlier value
    is zero or negative (a change of sign is not a growth rate)."""
    ends = _ends(st)
    rows = []
    for key, label in GROWTH_KEYS:
        s = _growth_series(st, key)
        if not s:
            continue
        all_ends = sorted(s)
        vals, whys = [], []
        for e in ends:
            prev = _year_before(all_ends, e)
            a, b = s.get(e), (s.get(prev) if prev else None)
            if a is None or b is None:
                vals.append(None)
                whys.append("No value a year earlier." if a is not None else None)
            elif b <= 0:
                vals.append(None)
                whys.append("Not meaningful: the earlier value is zero or negative.")
            else:
                vals.append((a / b - 1) * PCT)
                whys.append(None)
        rows.append(_row(f"g_{key}", label, "percent", f"{label} ÷ the value a year earlier − 1", vals, whys))
    return {"columns": ends, "rows": rows}


def cagr(st: dict, spans: tuple[int, ...] = (3, 5, 10)) -> dict:
    """Compound annual growth over 3, 5 and 10 fiscal years (annual statements only)."""
    if st.get("period") != "annual":
        return {"spans": list(spans), "rows": [], "note": "CAGR uses annual statements."}
    rows = []
    for key, label in GROWTH_KEYS:
        s = _growth_series(st, key)
        if not s:
            continue
        ends = sorted(s)
        last = ends[-1]
        vals, whys = [], []
        for n in spans:
            first = _year_before(ends, last, n)
            a, b = s.get(last), (s.get(first) if first else None)
            if b is None:
                vals.append(None)
                whys.append(f"Fewer than {n} years reported.")
            elif a is None or a <= 0 or b <= 0:
                vals.append(None)
                whys.append("Not meaningful: the start or end value is zero or negative.")
            else:
                vals.append((Decimal(str(float(a / b) ** (1 / n))) - 1) * PCT)
                whys.append(None)
        rows.append(
            {
                **_row(
                    f"cagr_{key}", label, "percent", f"({label} now ÷ {label} n years earlier)^(1/n) − 1", vals, whys
                ),
                "end": last,
            }  # fmt: skip
        )
    return {"spans": list(spans), "rows": rows}


def returns(st: dict) -> dict:
    """ROE, ROIC and cash conversion (annual statements only, ending balances)."""
    ends = _ends(st)
    if st.get("period") != "annual":
        return {
            "columns": ends,
            "rows": [],
            "note": "Returns use annual statements (quarterly figures are not annualized).",
        }
    ni, eq = series(st, "net_income"), series(st, "equity")
    op, pre, tax = series(st, "operating_income"), series(st, "pretax_income"), series(st, "income_tax")
    ltd, cd, cash = series(st, "long_term_debt"), series(st, "current_debt"), series(st, "cash")
    ocf = series(st, "operating_cash_flow")
    fcf = _fcf(st)
    roe, roic, roic_why, tax_rate, conv_ocf, conv_fcf = [], [], [], [], [], []
    for e in ends:
        n = _num(ni, e)
        roe.append(None if _div(n, _num(eq, e)) is None else _div(n, _num(eq, e)) * PCT)
        p, t = _num(pre, e), _num(tax, e)
        rate = _div(t, p) if p is not None and p > 0 else None
        ok_rate = rate is not None and ZERO <= rate <= Decimal("0.5")
        tax_rate.append(rate * PCT if ok_rate else None)
        o, q, c = _num(op, e), _num(eq, e), _num(cash, e)
        debts = [x for x in (_num(ltd, e), _num(cd, e)) if x is not None]
        why = None
        if o is None or q is None or c is None:
            why = "Operating income, equity or cash not reported."
        elif not debts:
            why = "Debt is not reported for this period, so invested capital is unknown (missing is not zero)."
        elif not ok_rate:
            why = "Effective tax rate unavailable or outside 0–50%."
        if why:
            roic.append(None)
        else:
            ic = q + sum(debts, ZERO) - c
            roic.append(None if ic <= 0 else o * (1 - rate) / ic * PCT)  # type: ignore[operator]
            why = "Invested capital is zero or negative." if ic <= 0 else None
        roic_why.append(why)
        conv_ocf.append(None if n is None or n <= 0 or _num(ocf, e) is None else _num(ocf, e) / n * PCT)  # type: ignore[operator]
        f = fcf.get(e)
        conv_fcf.append(None if n is None or n <= 0 or f is None else f / n * PCT)
    rows = [
        _row("roe", "Return on equity", "percent", "Net income ÷ period-end equity × 100", roe),
        _row(
            "roic",
            "Return on invested capital",
            "percent",
            "Operating income × (1 − tax rate) ÷ (equity + long-term debt + current debt − cash) × 100",
            roic,
            roic_why,
        ),  # fmt: skip
        _row("tax_rate", "Effective tax rate", "percent", "Income tax ÷ income before tax × 100", tax_rate),
        _row(
            "cash_conversion",
            "Cash conversion (OCF ÷ net income)",
            "percent",
            "Operating cash flow ÷ net income × 100 (only when net income is positive)",
            conv_ocf,
        ),  # fmt: skip
        _row(
            "fcf_conversion",
            "FCF conversion (FCF ÷ net income)",
            "percent",
            "Free cash flow ÷ net income × 100 (only when net income is positive)",
            conv_fcf,
        ),  # fmt: skip
    ]
    return {"columns": ends, "rows": rows}


# --------------------------------------------------------------------- valuation bands
def split_factor(splits: list[tuple[date, Decimal]], after: date, upto: date | None = None) -> Decimal:
    f = Decimal(1)
    for d, r in splits:
        if d > after and (upto is None or d <= upto) and r > 0:
            f *= r
    return f


def _first_filed(v: dict) -> date:
    dates = [_d(v["filed"])] + [_d(p["filed"]) for p in v.get("prior") or []]
    return min(dates)


def _stats(values: list[float], current: float | None) -> dict:
    if not values:
        return {"n": 0}
    s = sorted(values)
    q = statistics.quantiles(s, n=4) if len(s) >= 4 else [s[0], statistics.median(s), s[-1]]
    pct = None if current is None else sum(1 for x in s if x <= current) / len(s) * 100
    return {"n": len(s), "min": s[0], "p25": q[0], "median": q[1], "p75": q[2], "max": s[-1], "current": current,
            "percentile": pct}  # fmt: skip


def valuation_bands(
    annual: dict, bars: list[tuple[date, Decimal]], splits: list[tuple[date, Decimal]], price_currency: str | None
) -> dict:
    """Daily P/E and EV/EBITDA over the price history, using for each day the latest fiscal year already filed."""
    eps, op = series(annual, "eps_diluted"), series(annual, "operating_income")
    dep, shares = series(annual, "depreciation"), series(annual, "shares_diluted")
    ltd, cd, cash = series(annual, "long_term_debt"), series(annual, "current_debt"), series(annual, "cash")
    currency = annual.get("currency")
    if price_currency and currency and price_currency != currency:
        return {"pe": None, "ev_ebitda": None,
                "reason": f"Prices are in {price_currency} but the statements in {currency}; multiples would mix "
                          "currencies."}  # fmt: skip
    # P/E points: (available from, fiscal end, eps on today's share basis)
    pe_pts = []
    for end, v in eps.items():
        e = Decimal(str(v["value"]))
        pe_pts.append((_first_filed(v), end, e / split_factor(splits, _d(v["filed"]))))
    ev_pts = []
    for end, v in op.items():
        o, d, sh = _num(op, end), _num(dep, end), shares.get(end)
        debts = [x for x in (_num(ltd, end), _num(cd, end)) if x is not None]
        c = _num(cash, end)
        if o is None or d is None or sh is None or c is None or not debts:
            continue
        adj_sh = Decimal(str(sh["value"])) * split_factor(splits, _d(sh["filed"]))
        ev_pts.append((_first_filed(v), end, o + d, adj_sh, sum(debts, ZERO) - c))
    pe_pts.sort(key=lambda x: x[1])
    ev_pts.sort(key=lambda x: x[1])

    def latest(pts, day):
        known = [p for p in pts if p[0] <= day]
        return known[-1] if known else None

    pe_vals, ev_vals = [], []
    pe_cur = ev_cur = None
    for day, close in bars:
        p = latest(pe_pts, day)
        if p is not None and p[2] > 0:
            pe_cur = float(close / p[2])
            pe_vals.append(pe_cur)
        else:
            pe_cur = None
        q = latest(ev_pts, day)
        if q is not None and q[2] > 0:
            ev_cur = float((close * q[3] + q[4]) / q[2])
            ev_vals.append(ev_cur)
        else:
            ev_cur = None
    out = {
        "window": {"from": bars[0][0].isoformat(), "to": bars[-1][0].isoformat(), "sessions": len(bars)}
        if bars
        else None,
        "pe": {
            **_stats(pe_vals, pe_cur),
            "formula": "Close ÷ diluted EPS of the latest fiscal year filed by that day "
            "(EPS converted to today's share basis)",
            "why": None if pe_vals else "No positive annual EPS was filed during the price history.",
        },  # fmt: skip
        "ev_ebitda": {
            **_stats(ev_vals, ev_cur),
            "formula": "(Close × diluted shares + long-term and current debt − cash) ÷ "
            "(operating income + depreciation and amortization), latest fiscal year filed by that day",
            "why": None
            if ev_vals
            else "EBITDA, debt, cash or share count is missing, or EBITDA is not "
            "positive, for the years in the price history.",
        },  # fmt: skip
        "note": "Days use split-adjusted closes; each day uses the most recent annual report already filed (by filing "
        "date) with the latest reported value for that year; dividends are not included.",
    }
    return out


DAYS = Decimal(365)


def efficiency(st: dict) -> dict | None:
    """Capital efficiency and working capital (annual statements; ending balances), the measures Indian research
    sites lead with: ROCE, interest coverage, current ratio, debt to equity, dividend payout and the debtor,
    inventory and payable days that make up the cash conversion cycle. None when the source has none of the inputs
    (SEC data here does not map receivables, inventory or current liabilities)."""
    ends = _ends(st)
    if st.get("period") != "annual":
        return None
    g = {k: series(st, k) for k in ("operating_income", "total_assets", "current_liabilities", "interest_expense",
                                     "current_assets", "total_debt", "equity", "dividends_paid", "net_income",
                                     "receivables", "revenue", "inventory", "cost_of_revenue", "payables")}  # fmt: skip

    def col(f) -> list:
        out = []
        for e in ends:
            try:
                out.append(f({k: _num(v, e) for k, v in g.items()}))
            except (TypeError, ArithmeticError):
                out.append(None)
        return out

    def pct(a, b):
        q = _div(a, b)
        return None if q is None else q * PCT

    def days(a, b):
        q = _div(a, b)
        return None if q is None else q * DAYS

    def ce(x):  # capital employed = total assets − current liabilities
        return (
            None
            if x["total_assets"] is None or x["current_liabilities"] is None
            else x["total_assets"] - x["current_liabilities"]
        )

    def ccc(x):
        parts = [days(x["receivables"], x["revenue"]), days(x["inventory"], x["cost_of_revenue"]),
                 days(x["payables"], x["cost_of_revenue"])]  # fmt: skip
        return None if any(p is None for p in parts) else parts[0] + parts[1] - parts[2]

    rows = [
        _row("roce", "Return on capital employed", "percent",
             "Operating income ÷ (total assets − current liabilities) × 100",
             col(lambda x: pct(x["operating_income"], ce(x)) if (ce(x) or 0) > 0 else None)),
        _row("interest_coverage", "Interest coverage", "times", "Operating income ÷ interest expense",
             col(lambda x: _div(x["operating_income"], x["interest_expense"]) if (x["interest_expense"] or 0) > 0
                 else None)),
        _row("current_ratio", "Current ratio", "times", "Current assets ÷ current liabilities",
             col(lambda x: _div(x["current_assets"], x["current_liabilities"]))),
        _row("debt_equity", "Debt to equity", "times", "Total debt ÷ shareholders' equity",
             col(lambda x: _div(x["total_debt"], x["equity"]) if (x["equity"] or 0) > 0 else None)),
        _row("payout", "Dividend payout", "percent", "Dividends paid ÷ net income × 100",
             col(lambda x: pct(x["dividends_paid"], x["net_income"]) if (x["net_income"] or 0) > 0 else None)),
        _row("debtor_days", "Debtor days", "days", "Receivables ÷ revenue × 365",
             col(lambda x: days(x["receivables"], x["revenue"]))),
        _row("inventory_days", "Inventory days", "days", "Inventory ÷ cost of revenue × 365",
             col(lambda x: days(x["inventory"], x["cost_of_revenue"]))),
        _row("payable_days", "Payable days", "days", "Payables ÷ cost of revenue × 365",
             col(lambda x: days(x["payables"], x["cost_of_revenue"]))),
        _row("cash_conversion_cycle", "Cash conversion cycle", "days", "Debtor days + inventory days − payable days",
             col(ccc)),
    ]  # fmt: skip
    if not any(v is not None for r in rows for v in r["values"]):
        return None
    return {"columns": ends, "rows": rows}


def analysis(st: dict) -> dict:
    out = {
        "per_share": per_share(st),
        "common_size": common_size(st),
        "margins": margins(st),
        "growth": growth(st),
        "cagr": cagr(st),
        "returns": returns(st),
    }
    eff = efficiency(st)
    if eff is not None:
        out["efficiency"] = eff
    return out


# --------------------------------------------------------------------- provider statements (India and others)
def from_provider(periods: list, source: str) -> dict:
    """Provider annual statements (e.g. Yahoo's four fiscal years) in the normalized shape, so the same analysis runs.
    Only the lines the provider reports exist; everything else is reported as missing."""
    keys = {
        "revenue": "revenue",
        "net_income": "net_income",
        "equity": "total_equity",
        "long_term_debt": "total_debt",
        "operating_cash_flow": "operating_cash_flow",
        "capex": "capex",
        "cash": "cash",
    }
    lines = []
    for key, attr in keys.items():
        vals = []
        for p in periods:
            v = getattr(p, attr, None)
            if v is not None:
                vals.append({"value": v, "unit": "statement currency", "end": p.period_end, "start": None,
                             "form": source, "filed": None, "accession": None, "prior": []})  # fmt: skip
        lines.append({"key": key, "label": LABELS.get(key, key), "values": vals})
    return {
        "period": "annual",
        "period_ends": [p.period_end for p in periods],
        "currency": None,
        "lines": lines,
        "provider_note": "Total debt as reported by the provider is used in place of long-term plus current debt.",
    }

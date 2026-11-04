"""Portfolio performance, risk, exposure, correlations and rebalance simulations (M09).

All arithmetic lives in ``risk_math`` (pure, unit-tested); this module gathers the ledger, cached price history,
provider split history and exchange rates, and states every policy in the response.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import AllocationTarget, Instrument, ScreenMetric
from marketdesk.providers.base import HistoryRange
from marketdesk.services import risk_math as rm
from marketdesk.services.fx import USABLE, fx_symbol, valuation_rate
from marketdesk.services.ledger import CURRENCIES, LedgerEntry, TxnType, money
from marketdesk.services.market import MarketDataService
from marketdesk.services.portfolio import account_entries, all_transactions, portfolio_summary

ACCOUNTS = (*CURRENCIES, "ALL")
RANGE_DAYS: tuple[tuple[HistoryRange, int], ...] = (("1M", 28), ("3M", 89), ("6M", 180), ("1Y", 362), ("5Y", 1820))
US_BENCHMARK = "^GSPC"

POLICIES = [
    "Daily value = cash + quantity held at the end of the day × that day's as-traded close. The provider's closes are "
    "split-adjusted; MarketDesk restores as-traded prices with the provider's split history and applies the splits "
    "you recorded to the quantity, so a split is never counted twice.",
    "A close missing on a day (an exchange holiday) is carried forward for up to 10 calendar days; days beyond that "
    "are left out and their cash flows move to the next day that is included.",
    "Time-weighted return links daily returns r = (V_t − flows_t) ÷ V_(t−1) − 1, with deposits and withdrawals "
    "assumed at the end of their day. Money-weighted return is the XIRR of the same flows and the final value.",
    "Dividends you recorded are cash in the account, so they count in the portfolio's return. The benchmark is a "
    "price index and excludes dividends.",
    "Annualized figures appear only for periods of at least a year; volatility (daily, × √252) needs at least 60 "
    "daily returns. Cash earns nothing here (no interest is modelled).",
]


def _pct(x: float | None, places: int = 2) -> str | None:
    return None if x is None or math.isnan(x) else f"{x * 100:.{places}f}"


def _range_for(days: int) -> HistoryRange:
    for r, d in RANGE_DAYS:
        if days <= d:
            return r
    return "5Y"


def _default_benchmark(market: MarketDataService, settings, account: str) -> str:
    from marketdesk.api.routes_market import benchmark_symbols

    if account == "USD" and market.source == "yahoo":
        return US_BENCHMARK
    return benchmark_symbols(settings, market)[0]


async def _closes(market: MarketDataService, symbol: str, range_: HistoryRange, adjust: bool = True):
    """({day: as-traded close}, provider splits, PriceHistory result)."""
    hist = await market.history(symbol, range_)
    if hist.value is None or hist.meta.status not in USABLE:
        return None, [], hist
    splits = []
    if adjust:
        acts = await market.actions(symbol)
        splits = [(a.action_date, a.value) for a in (acts.value or []) if a.kind == "SPLIT"]
    raw = [(b.session_date, b.close) for b in hist.value.bars]
    return rm.as_traded(raw, splits), splits, hist


def _symbols(entries: list[LedgerEntry]) -> list[str]:
    return sorted({e.symbol for e in entries if e.symbol})


def _split_warnings(entries: list[LedgerEntry], splits: dict[str, list]) -> list[str]:
    out = []
    for sym, sp in splits.items():
        held = [e.effective_date for e in entries if e.symbol == sym and e.type == TxnType.BUY]
        if not held:
            continue
        recorded = [e.effective_date for e in entries if e.symbol == sym and e.type == TxnType.SPLIT]
        for d, ratio in sp:
            if d >= min(held) and not any(abs((d - r).days) <= 5 for r in recorded):
                out.append(
                    f"{sym}: the provider reports a {ratio}-for-1 split on {d.isoformat()} that is not recorded in "
                    "the ledger; values after it are understated until you record the split."
                )
    return out


async def performance(db: Session, market: MarketDataService, settings, account: str, benchmark: str | None) -> dict:
    if account not in ACCOUNTS:
        raise AppError(422, "bad_account", "Account is INR, USD or ALL.")
    entries_by = account_entries(all_transactions(db))
    accounts = [c for c in CURRENCIES if entries_by.get(c)] if account == "ALL" else [account]
    entries = {c: entries_by.get(c, []) for c in accounts}
    if not any(entries.values()):
        return {"available": False, "account": account, "reason": "No transactions in this account yet."}
    base = "INR" if account == "ALL" else account
    start = min(e.effective_date for es in entries.values() for e in es)
    today = datetime.now(UTC).date()
    range_ = _range_for((today - start).days)
    notes: list[str] = []
    if (today - start).days > RANGE_DAYS[-1][1]:
        notes.append("Price history covers the last five years; earlier days are not valued.")

    syms = sorted({s for es in entries.values() for s in _symbols(es)})
    fetched = await asyncio.gather(*(_closes(market, s, range_) for s in syms))
    prices, splits, missing_hist = {}, {}, []
    for s, (closes, sp, hist) in zip(syms, fetched, strict=True):
        if closes:
            prices[s] = rm.CloseLookup(closes)
            splits[s] = sp
        else:
            missing_hist.append(f"{s} ({hist.meta.message or hist.meta.status})")
    bench_sym = benchmark or _default_benchmark(market, settings, account)
    try:
        bench_sym = market.validate_symbol(bench_sym)
        bench_closes, _, bench_hist = await _closes(market, bench_sym, range_, adjust=False)
    except Exception:  # an invalid benchmark must not break the portfolio view
        bench_closes, bench_hist = None, None

    calendar = sorted({d for lk in prices.values() for d in lk.days} | set(bench_closes or {}))
    calendar = [d for d in calendar if d >= start]
    fx_map = None
    if account == "ALL" and "USD" in accounts:
        sym = fx_symbol(market.source, "USD", "INR")
        fx_closes = (await _closes(market, sym, range_, adjust=False))[0] if sym else None
        if not fx_closes:
            return {
                "available": False,
                "account": account,
                "reason": "No USD/INR history is available to value the "
                "USD account in INR day by day; see each account separately.",
            }
        lk = rm.CloseLookup(fx_closes)
        fx_map = {d: r for d in calendar if (r := lk.at(d)) is not None}
        notes.append(
            f"USD values are converted at each day's USD/INR close ({sym}); FX conversions between your "
            "accounts are internal transfers, so only their fees and rate differences affect the return."
        )

    consolidated = account == "ALL"
    series_by = {c: rm.value_series(entries[c], prices, calendar, consolidated=consolidated) for c in accounts}
    series = (
        rm.combine([(series_by[c], fx_map if c == "USD" else None) for c in accounts])
        if consolidated
        else series_by[account]
    )
    points = series.points
    if len(points) < 2:
        return {
            "available": False,
            "account": account,
            "reason": "Not enough valued days yet (a performance series "
            "needs at least two days with prices for every holding).",
            "missing_history": missing_hist,
        }

    index, rets = rm.twr_index(points)
    first, last = points[0], points[-1]
    days = (last.day - first.day).days
    twr = index[-1][1] / 100.0 - 1.0
    mwr = rm.xirr(series.flows, last.day, last.value)
    mwr_period = (1.0 + mwr) ** (days / 365.0) - 1.0 if mwr is not None else None
    vol = rm.volatility([r for _, r in rets])
    dd = rm.drawdowns(index)
    best = max(rets, key=lambda x: x[1]) if rets else None
    worst = min(rets, key=lambda x: x[1]) if rets else None

    bench = None
    bench_index: list[float | None] = []
    if bench_closes:
        blk = rm.CloseLookup(bench_closes)
        b0 = blk.at(first.day)
        levels = [(p.day, blk.at(p.day)) for p in points]
        bench_index = [round(float(v / b0) * 100, 4) if (v is not None and b0) else None for _, v in levels]
        b_rets = [
            (d1, float(v1 / v0) - 1.0)
            for (_, v0), (d1, v1) in zip(levels, levels[1:], strict=False)
            if v0 is not None and v1 is not None and v0 > 0
        ]
        b_total = float(levels[-1][1] / b0) - 1.0 if (b0 and levels[-1][1] is not None) else None
        # A "market" is the exchange time zone: daily closes in different time zones are not simultaneous.
        held = list(db.scalars(select(Instrument).where(Instrument.symbol.in_(syms)))) if syms else []
        markets = {i.timezone or i.country for i in held}
        b_inst = bench_hist.value.instrument if bench_hist and bench_hist.value else None  # type: ignore[union-attr]
        b_market = getattr(b_inst, "timezone", None) or getattr(b_inst, "country", None)
        same_market = bool(held) and len(markets) == 1 and None not in markets and (b_market in (None, *markets))
        beta = corr = None
        n = 0
        if same_market:
            beta, corr, n = rm.beta(rets, b_rets)
        b_levels = [(d, v / 100) for (d, _), v in zip(levels, bench_index, strict=True) if v is not None]
        bdd = rm.drawdowns([(d, v * 100) for d, v in b_levels]) if b_levels else None
        bench = {
            "symbol": bench_sym,
            "name": getattr(b_inst, "name", None),
            "currency": getattr(b_inst, "currency", None),
            "total_pct": _pct(b_total),
            "annualized_pct": _pct(rm.annualize(b_total, days)) if b_total is not None else None,
            "volatility_pct": _pct(rm.volatility([r for _, r in b_rets])),
            "max_drawdown_pct": _pct(bdd["max"]["depth"]) if bdd else None,
            "excess_pct": _pct(twr - b_total) if b_total is not None else None,
            "beta": None if beta is None else f"{beta:.2f}",
            "correlation": None if corr is None else f"{corr:.2f}",
            "n": n,
            "beta_note": None
            if same_market
            else "Beta and correlation are shown only when every holding trades on the benchmark's market (closing "
            "times differ across exchanges).",
            "currency_note": (
                f"The benchmark is quoted in {getattr(b_inst, 'currency', '?')}; returns are compared in each own "
                "currency."
            )
            if getattr(b_inst, "currency", None) and getattr(b_inst, "currency", None) != base
            else None,
        }
    else:
        notes.append(f"No price history for the benchmark {bench_sym}; comparison not shown.")

    mx = dd["max"]
    return {
        "available": True,
        "account": account,
        "currency": base,
        "start": first.day.isoformat(),
        "end": last.day.isoformat(),
        "days": days,
        "observations": len(rets),
        "metrics": {
            "end_value": str(money(last.value)),
            "net_flows": str(money(sum((f for _, f in series.flows), Decimal(0)))),
            "flows_count": len(series.flows),
            "twr_pct": _pct(twr),
            "twr_annualized_pct": _pct(rm.annualize(twr, days)),
            "mwr_annualized_pct": _pct(mwr) if days >= 365 else None,
            "mwr_period_pct": _pct(mwr_period),
            "volatility_pct": _pct(vol),
            "max_drawdown": {
                "depth_pct": _pct(mx["depth"]),
                "peak": mx["peak"].isoformat() if mx["peak"] else None,
                "trough": mx["trough"].isoformat() if mx["trough"] else None,
                "recovered": mx["recovered"].isoformat() if mx["recovered"] else None,
            },
            "current_drawdown_pct": _pct(dd["current"]),
            "best_day": {"day": best[0].isoformat(), "pct": _pct(best[1])} if best else None,
            "worst_day": {"day": worst[0].isoformat(), "pct": _pct(worst[1])} if worst else None,
        },
        "benchmark": bench,
        "series": {
            "dates": [p.day.isoformat() for p in points],
            "value": [str(money(p.value)) for p in points],
            "index": [round(v, 4) for _, v in index],
            "benchmark": bench_index,
            "underwater": [round(v * 100, 4) for _, v in dd["underwater"]],
        },
        "skipped": {
            "count": len(series.skipped),
            "examples": [f"{d.isoformat()}: {why}" for d, why in series.skipped[:3]],
        },
        "missing_history": missing_hist,
        "warnings": _split_warnings([e for es in entries.values() for e in es], splits),
        "notes": notes,
        "policies": POLICIES,
        "source": market.source,
    }


# --------------------------------------------------------------------- exposure
async def exposure(db: Session, market: MarketDataService, account: str) -> dict:
    if account not in ACCOUNTS:
        raise AppError(422, "bad_account", "Account is INR, USD or ALL.")
    ccys = list(CURRENCIES) if account == "ALL" else [account]
    base = "INR" if account == "ALL" else account
    items, unpriced, cash_total, rates = [], [], Decimal(0), {}
    for c in ccys:
        s = await portfolio_summary(db, market, c)
        if not s["has_transactions"]:
            continue
        rate = Decimal(1)
        if c != base:
            fx = await valuation_rate(market, c, base)
            rates[f"{c}/{base}"] = fx
            if fx.get("rate") is None:
                unpriced.append(f"the {c} account (no {c}/{base} rate)")
                continue
            rate = fx["rate"]
        cash_total += s["cash"] * rate
        for h in s["holdings"]:
            if h["market_value"] is None:
                unpriced.append(h["symbol"])
                continue
            items.append({"symbol": h["symbol"], "name": h["name"], "currency": c, "value": h["market_value"] * rate})
    if not items and cash_total == 0:
        return {"available": False, "account": account, "reason": "No holdings or cash in this account yet."}
    insts = {
        i.symbol: i for i in db.scalars(select(Instrument).where(Instrument.symbol.in_([x["symbol"] for x in items])))
    }
    snaps = {
        r.instrument_id: r.values
        for r in db.scalars(select(ScreenMetric).where(ScreenMetric.instrument_id.in_([i.id for i in insts.values()])))
    }
    for x in items:
        inst = insts.get(x["symbol"])
        sector = (snaps.get(inst.id) or {}).get("sector") if inst else None
        if sector is None and inst is not None:
            f = await market.fundamentals(inst.symbol)
            sector = f.value.sector if f.value is not None else None
        x["sector"] = sector or "Not reported"
        x["country"] = (inst.country if inst else None) or "Unknown"
    invested = sum((x["value"] for x in items), Decimal(0))
    total = invested + cash_total

    def buckets(key: str) -> list[dict]:
        agg: dict[str, Decimal] = {}
        for x in items:
            agg[x[key]] = agg.get(x[key], Decimal(0)) + x["value"]
        rows = [
            {
                "name": k,
                "value": str(money(v)),
                "pct_of_total": _pct(float(v / total)) if total else None,
                "pct_of_invested": _pct(float(v / invested)) if invested else None,
            }
            for k, v in agg.items()
        ]
        return sorted(rows, key=lambda r: -float(r["value"]))

    weights = sorted((float(x["value"] / invested) for x in items), reverse=True) if invested else []
    hhi = sum(w * w for w in weights)
    return {
        "available": True,
        "account": account,
        "currency": base,
        "total": str(money(total)),
        "invested": str(money(invested)),
        "cash": str(money(cash_total)),
        "cash_pct": _pct(float(cash_total / total)) if total else None,
        "by_holding": buckets("symbol"),
        "by_sector": buckets("sector"),
        "by_country": buckets("country"),
        "by_currency": buckets("currency"),
        "concentration": {
            "largest_pct": _pct(weights[0]) if weights else None,
            "top5_pct": _pct(sum(weights[:5])) if weights else None,
            "hhi": f"{hhi:.3f}" if weights else None,
            "effective_holdings": f"{1 / hhi:.1f}" if hhi else None,
            "formula": "Weights are shares of the invested value. HHI = Σ weight²; effective number of holdings "
            "= 1 ÷ HHI.",
        },
        "unpriced": unpriced,
        "rates": rates,
        "note": "Current market values at the latest marks; other-currency holdings converted at the current rate "
        "shown (for display only). Sectors come from the provider's classification.",
    }


# --------------------------------------------------------------------- correlations
async def correlations(db: Session, market: MarketDataService, settings, account: str, benchmark: str | None) -> dict:
    ccys = list(CURRENCIES) if account == "ALL" else [account]
    symbols: list[str] = []
    for c in ccys:
        s = await portfolio_summary(db, market, c)
        symbols += [h["symbol"] for h in s["holdings"] if h["symbol"] not in symbols]
    if not symbols:
        return {"available": False, "reason": "Correlations need at least one holding."}
    bench = benchmark or _default_benchmark(market, settings, "INR" if account == "ALL" else account)
    members = symbols[:12] + ([bench] if bench not in symbols else [])
    fetched = await asyncio.gather(*(_closes(market, s, "1Y") for s in members))
    closes = {s: c for s, (c, _, _) in zip(members, fetched, strict=True) if c}
    insts = {i.symbol: i for i in db.scalars(select(Instrument).where(Instrument.symbol.in_(members)))}

    def market_of(s: str) -> str | None:
        i = insts.get(s)
        return (i.timezone or i.country) if i else None

    cells = []
    names = [s for s in members if s in closes]
    for a in names:
        row = []
        for b in names:
            if a == b:
                row.append({"r": "1.00", "n": len(closes[a]), "method": "same"})
                continue
            same = market_of(a) is not None and market_of(a) == market_of(b)
            c = rm.correlation(closes[a], closes[b], same)
            row.append({**c, "r": None if c["r"] is None else f"{c['r']:.2f}"})
        cells.append(row)
    return {
        "available": True,
        "symbols": names,
        "benchmark": bench if bench in names else None,
        "matrix": cells,
        "missing": [s for s in members if s not in closes],
        "truncated": max(0, len(symbols) - 12),
        "window": "One year of daily closes.",
        "method": "Pearson correlation of simple returns. Same exchange time zone: daily returns between consecutive "
        "dates on which both traded (no carried-forward prices; at least 60). Different exchanges: weekly returns from "
        "each week's last close (at least 26), because daily closes on different exchanges are not simultaneous.",
    }


# --------------------------------------------------------------------- targets / rebalance
def get_targets(db: Session, account: str) -> list[dict]:
    rows = db.scalars(
        select(AllocationTarget).where(AllocationTarget.currency == account).order_by(AllocationTarget.symbol)
    )
    return [{"symbol": r.symbol, "target_pct": format(r.target_pct.quantize(Decimal("0.01")), "f")} for r in rows]


def set_targets(db: Session, account: str, targets: list[dict]) -> list[dict]:
    if account not in CURRENCIES:
        raise AppError(422, "bad_account", "Targets are set per account (INR or USD).")
    seen: dict[str, Decimal] = {}
    for t in targets:
        sym = str(t.get("symbol") or "").strip().upper()
        try:
            pct = Decimal(str(t.get("target_pct")))
        except Exception as err:
            raise AppError(422, "bad_target", f"Target for {sym or '?'} must be a number.") from err
        if not sym or not (Decimal(0) <= pct <= Decimal(100)) or not pct.is_finite():
            raise AppError(422, "bad_target", f"Target for {sym or '?'} must be between 0 and 100%.")
        if sym in seen:
            raise AppError(422, "bad_target", f"{sym} appears twice.")
        seen[sym] = pct.quantize(Decimal("0.01"))
    if sum(seen.values(), Decimal(0)) > 100:
        raise AppError(422, "bad_target", "Targets add up to more than 100%.")
    for row in db.scalars(select(AllocationTarget).where(AllocationTarget.currency == account)):
        db.delete(row)
    db.flush()
    for sym, pct in seen.items():
        db.add(AllocationTarget(currency=account, symbol=sym, target_pct=pct))
    db.commit()
    return get_targets(db, account)


async def simulate(
    db: Session, market: MarketDataService, account: str, extra_cash: Decimal, whole_shares: bool, fee_pct: Decimal
) -> dict:
    if account not in CURRENCIES:
        raise AppError(422, "bad_account", "Rebalancing is simulated per account (INR or USD).")
    s = await portfolio_summary(db, market, account)
    targets = {t["symbol"]: Decimal(t["target_pct"]) for t in get_targets(db, account)}
    holdings = [rm.Holding(h["symbol"], h["quantity"], h["last_price"]) for h in s["holdings"]]
    out = rm.rebalance(holdings, s["cash"], targets, extra_cash=extra_cash, whole_shares=whole_shares, fee_pct=fee_pct)

    def d(v):
        return None if v is None else format(v.quantize(Decimal("0.0001")) if isinstance(v, Decimal) else v, "f")

    return {
        "account": account,
        "currency": account,
        "total": d(out["total"]),
        "cash_before": d(out["cash_before"]),
        "extra_cash": d(out["extra_cash"]),
        "cash_after": d(out["cash_after"]),
        "cash_weight_after_pct": d(out["cash_weight_after_pct"]),
        "fees": d(out["fees"]),
        "target_sum_pct": d(out["target_sum_pct"]),
        "rows": [{k: (d(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in out["rows"]],
        "unpriced": out["unpriced"],
        "targets_without_holding": out["targets_without_holding"],
        "warnings": out["warnings"],
        "note": "A simulation only: no orders are placed. Trades use the latest marks"
        + (", rounded toward zero to whole shares" if whole_shares else "")
        + (f", with an assumed {fee_pct}% fee per trade" if fee_pct else "")
        + "; anything not targeted stays in cash.",
        "marks_complete": s["complete"],
    }

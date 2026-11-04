"""Research lab (M13): reproducible rule tests and an isolated paper portfolio. Everything here is simulated.

The arithmetic lives in ``sim_math``; this module fetches the provider's daily bars and corporate actions, records
each run with the data fingerprint, and replays paper orders on read (fills at the next session's open)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import PaperOrder, PaperPortfolio, ResearchRun
from marketdesk.services import sim_math as sm
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService

USABLE = {"sample", "available", "cached", "stale"}
SIMULATED = "Simulated: no orders are sent anywhere and nothing here enters your real ledger."
REVIEW = [
    {
        "title": "Signals precede execution",
        "text": "A rule decides at a session's close and trades at the next session's open. Filling at the close that "
        "produced the signal would assume you could act on information before it existed (look-ahead).",
    },
    {
        "title": "Sample limits",
        "text": "Five years of daily bars is a short, single history. One market regime can dominate the result; a "
        "rule that worked here may not work elsewhere or later. Few trades make the result fragile.",
    },
    {
        "title": "Survivorship bias",
        "text": "You test companies that exist and are listed today. Companies that failed or were delisted are "
        "missing, which makes historical tests look better than investing at the time would have been.",
    },
    {
        "title": "Overfitting",
        "text": "Trying many parameter values and keeping the best one finds noise. Prefer simple rules, few "
        "parameters and a check on a period you did not tune on.",
    },
    {
        "title": "Costs and fills",
        "text": "Fees and slippage are your assumptions. Real fills depend on liquidity, spreads and order type; the "
        "next-open price is a simplification. Taxes are not modelled; cash earns nothing.",
    },
    {
        "title": "Data basis",
        "text": "Prices are the provider's split-adjusted daily bars (dividends credited separately in rule tests). "
        "Fundamentals are today's values only, so no test here uses historical fundamentals or claims to be "
        "point-in-time.",
    },
]


def _costs(fee_pct, slippage_bps) -> sm.Costs:
    fee, slip = Decimal(str(fee_pct)), Decimal(str(slippage_bps))
    if not (Decimal(0) <= fee <= Decimal(2)) or not (Decimal(0) <= slip <= Decimal(200)):
        raise AppError(422, "bad_costs", "Fees must be 0–2% and slippage 0–200 basis points.")
    return sm.Costs(fee, slip)


async def _series(market: MarketDataService, symbol: str) -> tuple[list[sm.Bar], dict, list, dict]:
    hist, acts = await asyncio.gather(market.history(symbol, "5Y"), market.actions(symbol))
    if hist.value is None or hist.meta.status not in USABLE:
        raise AppError(422, "no_history", hist.meta.message or "No daily history is available for this symbol.")
    bars = [sm.Bar(b.session_date, b.open, b.close) for b in hist.value.bars if b.open is not None]
    dropped = len(hist.value.bars) - len(bars)
    splits = [(a.action_date, a.value) for a in (acts.value or []) if a.kind == "SPLIT"]
    divs = [(a.action_date, a.value) for a in (acts.value or []) if a.kind == "DIVIDEND"]
    info = {
        "provider": market.source,
        "range": "5Y",
        "adjustment": hist.value.adjustment,
        "bars": len(bars),
        "dropped_without_open": dropped,
        "status": hist.meta.status,
        "fetched_at": hist.meta.fetched_at.isoformat() if hist.meta.fetched_at else None,
        "currency": hist.value.instrument.currency,
        "country": hist.value.instrument.country,
    }
    return bars, sm.adjusted_dividends(divs, splits), splits, info


def _num(x):
    if isinstance(x, Decimal):
        return format(x.quantize(Decimal("0.0001")), "f")
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, dict):
        return {k: _num(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_num(v) for v in x]
    if isinstance(x, tuple):
        return [_num(v) for v in x]
    if isinstance(x, date):
        return x.isoformat()
    return x


def _completed(bars: list[sm.Bar], divs: dict, info: dict) -> tuple[list[sm.Bar], dict]:
    """A rule decides on a session's close, so an unfinished latest session (its 'close' is the latest price) is left
    out; dividends are kept only where the test could credit them (after the first bar, up to the last)."""
    from marketdesk.services.alerts import last_bar_complete

    if bars and not last_bar_complete(info.get("country"), bars[-1].day, datetime.now(UTC)):
        info["unfinished_session_excluded"] = bars[-1].day.isoformat()
        bars = bars[:-1]
        info["bars"] = len(bars)
    if bars:
        divs = {d: v for d, v in divs.items() if bars[0].day < d <= bars[-1].day}
    return bars, divs


def _thin(equity: list, points: int = 400) -> list:
    """Every n-th point for the chart, always ending on the last session so the line ends at the table's value."""
    step = max(1, len(equity) // points)
    out = equity[::step]
    if equity and out[-1] is not equity[-1]:
        out = [*out, equity[-1]]
    return [[d, v] for d, v in out]


async def compute(
    market: MarketDataService,
    symbol: str,
    rule: str,
    params: dict,
    costs: sm.Costs,
    cash0: Decimal,
    benchmark: str | None,
) -> tuple[dict, dict]:
    bars, divs, _, info = await _series(market, symbol)
    bars, divs = _completed(bars, divs, info)
    if len(bars) < 60:
        raise AppError(422, "short_history", f"Only {len(bars)} daily bars; a rule test needs at least 60.")
    info.update(
        first=bars[0].day.isoformat(), last=bars[-1].day.isoformat(), hash=sm.data_hash(bars, divs), dividends=len(divs)
    )
    strat = sm.run_rule(bars, rule, params, costs, cash0, divs)
    hold = sm.run_rule(bars, "buy_and_hold", {}, costs, cash0, divs)
    results = {
        "strategy": {
            **sm.summarize(strat["equity"], cash0),
            "trades": len(strat["trades"]),
            "exposure_pct": strat["exposure_pct"],
            "fees": sum((t["fee"] for t in strat["trades"]), Decimal(0)),
        },
        "buy_and_hold": {**sm.summarize(hold["equity"], cash0), "trades": len(hold["trades"])},
        "trades": strat["trades"][-50:],
        "equity": _thin(strat["equity"]),
        "hold_equity": _thin(hold["equity"]),
    }
    if benchmark and benchmark != symbol:
        try:
            bb, bd, _, binfo = await _series(market, benchmark)
            bb = [b for b in bb if bars[0].day <= b.day <= bars[-1].day]
            bd = {d: v for d, v in bd.items() if bb and bb[0].day < d <= bb[-1].day}
            if len(bb) >= 60:
                bench = sm.run_rule(bb, "buy_and_hold", {}, sm.Costs(), cash0, bd)
                results["benchmark"] = {"symbol": benchmark, **sm.summarize(bench["equity"], cash0)}
        except AppError:
            results["benchmark"] = {"symbol": benchmark, "error": "No usable history for the benchmark."}
    return _num(results), info


async def run_test(db: Session, market: MarketDataService, settings, body: dict) -> ResearchRun:
    inst = await resolve_instrument(db, market, body["symbol"])
    try:
        params = sm.validate_params(body["rule"], body.get("params") or {})
    except ValueError as err:
        raise AppError(422, "bad_rule", str(err)) from err
    costs = _costs(body.get("fee_pct", 0), body.get("slippage_bps", 0))
    cash0 = Decimal(str(body.get("starting_cash", 100000)))
    if not Decimal(1000) <= cash0 <= Decimal("1e12"):
        raise AppError(422, "bad_cash", "Starting cash must be between 1,000 and 10^12.")
    from marketdesk.api.routes_market import benchmark_symbols

    bench = body.get("benchmark") or (
        benchmark_symbols(settings, market)[0] if inst.country != "US" or market.source == "fixture" else "^GSPC"
    )
    results, info = await compute(market, inst.symbol, body["rule"], params, costs, cash0, bench)
    run = ResearchRun(
        symbol=inst.symbol,
        rule=body["rule"],
        params=params,
        costs={
            "fee_pct": str(costs.fee_pct),
            "slippage_bps": str(costs.slippage_bps),
            "starting_cash": str(cash0),
            "benchmark": bench,
        },
        data=info,
        results=results,
    )
    db.add(run)
    db.commit()
    return run


async def reproduce(db: Session, market: MarketDataService, run: ResearchRun) -> dict:
    c = run.costs
    results, info = await compute(
        market,
        run.symbol,
        run.rule,
        run.params,
        sm.Costs(Decimal(c["fee_pct"]), Decimal(c["slippage_bps"])),
        Decimal(c["starting_cash"]),
        c.get("benchmark"),
    )
    same_data = info["hash"] == run.data.get("hash")
    same = results["strategy"] == run.results["strategy"] and results["buy_and_hold"] == run.results["buy_and_hold"]
    return {
        "same_data": same_data,
        "same_results": same,
        "data_now": info,
        "data_then": run.data,
        "explanation": "Identical data and identical results."
        if same_data and same
        else (
            "The data changed since the run (new bars, restated prices or new corporate actions), so results may "
            "differ."
            if not same_data
            else "Same data but different results: the calculation changed."
        ),
    }


def run_dict(r: ResearchRun, full: bool = True) -> dict:
    d = {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "symbol": r.symbol,
        "rule": r.rule,
        "params": r.params,
        "costs": r.costs,
        "data": r.data,
        "summary": {k: r.results.get(k) for k in ("strategy", "buy_and_hold", "benchmark")},
    }
    if full:
        d["results"] = r.results
    d["label"] = SIMULATED
    return d


# --------------------------------------------------------------------- paper
async def paper_state(db: Session, market: MarketDataService, pf: PaperPortfolio) -> dict:
    syms = sorted({o.symbol for o in pf.orders})
    series = dict(zip(syms, await asyncio.gather(*(_series(market, s) for s in syms)), strict=True)) if syms else {}
    bars_by = {s: v[0] for s, v in series.items()}
    orders = []
    for o in pf.orders:
        splits = series[o.symbol][2] if o.symbol in series else []
        factor = Decimal(1)
        for d, r in splits:
            if d > o.placed_session and r > 0:
                factor *= r
        orders.append(sm.Order(o.id, o.side, o.symbol, o.quantity * factor, o.placed_session))
    costs = sm.Costs(pf.fee_pct, pf.slippage_bps)
    st = sm.fill_orders(orders, bars_by, costs, pf.starting_cash)
    positions, value = [], st["cash"]
    for sym, qty in st["positions"].items():
        last = bars_by[sym][-1]
        mv = qty * last.close
        value += mv
        positions.append(
            {
                "symbol": sym,
                "quantity": qty,
                "last_close": last.close,
                "as_of": last.day.isoformat(),
                "market_value": mv,
                "cost": st["cost"].get(sym),
            }
        )
    order_rows = []
    for o in pf.orders:
        res = st["orders"].get(o.id, {})
        order_rows.append(
            {
                "id": o.id,
                "side": o.side,
                "symbol": o.symbol,
                "quantity": o.quantity,
                "placed_at": o.placed_at.isoformat() if o.placed_at else None,
                "placed_session": o.placed_session.isoformat(),
                **res,
            }
        )
    return _num(
        {
            "id": pf.id,
            "name": pf.name,
            "currency": pf.currency,
            "starting_cash": pf.starting_cash,
            "fee_pct": pf.fee_pct,
            "slippage_bps": pf.slippage_bps,
            "cash": st["cash"],
            "positions": positions,
            "value": value,
            "return_pct": (value / pf.starting_cash - 1) * 100,
            "orders": order_rows,
            "label": SIMULATED,
            "method": "Orders fill at the next session's open after the latest session known when they were placed, "
            "plus slippage, with the fee from cash. Quantities are converted with later splits; dividends are not "
            "credited in the paper portfolio.",
        }
    )


async def place_order(
    db: Session, market: MarketDataService, pf: PaperPortfolio, side: str, symbol: str, quantity: Decimal
) -> PaperOrder:
    inst = await resolve_instrument(db, market, symbol)
    if (inst.currency or pf.currency) != pf.currency:
        raise AppError(
            422,
            "currency_mismatch",
            f"{inst.symbol} trades in {inst.currency}; this paper portfolio is in {pf.currency}.",
        )
    if quantity <= 0 or quantity != quantity.to_integral_value():
        raise AppError(422, "bad_quantity", "Use a whole number of shares greater than zero.")
    bars, _, _, _ = await _series(market, inst.symbol)
    if not bars:
        raise AppError(422, "no_history", "No daily bars to fill against.")
    o = PaperOrder(portfolio_id=pf.id, side=side, symbol=inst.symbol, quantity=quantity, placed_session=bars[-1].day)
    db.add(o)
    db.commit()
    return o

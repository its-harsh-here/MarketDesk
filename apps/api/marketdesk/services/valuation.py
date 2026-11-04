"""Valuation lab (M11): DCF defaults with their sources, DCF and sensitivity, peer-multiple ranges, saved scenarios
and portfolio stress tests. Arithmetic lives in ``valuation_math``; every output is labelled hypothetical."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Instrument, PeerSet, ScreenMetric, ValuationScenario
from marketdesk.services import valuation_math as vm
from marketdesk.services.fx import USABLE, valuation_rate
from marketdesk.services.instruments import find_instrument, resolve_instrument
from marketdesk.services.ledger import CURRENCIES
from marketdesk.services.market import MarketDataService
from marketdesk.services.portfolio import portfolio_summary

FINANCIAL = {"financial services", "financial", "financials"}
TZ_MARKET = {"Asia/Kolkata": "IN", "America/New_York": "US", "America/Chicago": "US"}
HYPOTHETICAL = (
    "Hypothetical: these values follow from the assumptions you enter. They are not fair values, forecasts or "
    "recommendations."
)
NOT_FOR_FINANCIALS = (
    "A generic free-cash-flow DCF is not applied to banks, lenders and insurers: borrowing and float are their "
    "operating business, so free cash flow is not a meaningful measure. Use peer multiples (P/B) instead."
)
DEFAULT_RATES = {"INR": (Decimal(12), Decimal(4)), "USD": (Decimal(9), Decimal("2.5"))}  # (cost of equity, terminal g)


def _s(v: Decimal | None, places: int = 4) -> str | None:
    return None if v is None else format(v.quantize(Decimal(10) ** -places), "f")


def market_of(inst: Instrument) -> str:
    return inst.country or TZ_MARKET.get(inst.timezone or "", "Other")


async def inputs(db: Session, market: MarketDataService, symbol: str) -> dict:
    inst = await resolve_instrument(db, market, symbol)
    quote, fund, st = (
        await market.quote(inst.symbol),
        await market.fundamentals(inst.symbol),
        await market.statements(inst.symbol),
    )
    price = quote.value.last_price if quote.value is not None and quote.meta.status in USABLE else None
    f = fund.value if fund.value is not None and fund.meta.status in USABLE else None
    sector = f.sector if f else None
    periods = st.value.periods if st.value is not None and st.meta.status in USABLE else []
    p0 = periods[0] if periods else None
    ccy = inst.currency or "INR"
    defaults: dict[str, dict] = {}

    if p0 and p0.operating_cash_flow is not None and p0.capex is not None:
        fcf = p0.operating_cash_flow - p0.capex
        defaults["fcf0"] = {
            "value": _s(fcf, 0),
            "source": f"{st.value.source}: operating cash flow − capital expenditure, "  # type: ignore[union-attr]
            f"fiscal year ending {p0.period_end.isoformat()}",
        }
        if fcf <= 0:
            defaults["fcf0"]["warning"] = (
                "The latest reported free cash flow is not positive; enter a normalized figure to run a DCF."
            )
    else:
        defaults["fcf0"] = {"value": None, "source": "Not reported by the provider: enter a figure."}
    if f and f.market_cap and price:
        defaults["shares"] = {"value": _s(f.market_cap / price, 0), "source": "Implied: market cap ÷ last price"}
    else:
        defaults["shares"] = {"value": None, "source": "Market cap or price unavailable: enter shares outstanding."}
    g = None
    if len(periods) > 1 and periods[0].revenue and periods[1].revenue and periods[1].revenue > 0:
        g = (periods[0].revenue / periods[1].revenue - 1) * 100
    if g is not None:
        defaults["growth_pct"] = {
            "value": _s(min(max(g, Decimal(0)), Decimal(15)), 1),
            "source": f"Latest fiscal-year revenue growth ({_s(g, 1)}%), limited to 0–15%",
        }
    else:
        defaults["growth_pct"] = {"value": "5.0", "source": "Assumption (no revenue history to start from)"}
    coe, tg = DEFAULT_RATES.get(ccy, (Decimal(10), Decimal(3)))
    defaults["discount_pct"] = {
        "value": _s(coe, 1),
        "source": f"Assumption: a round cost of equity for {ccy} equities; set your own",
    }
    defaults["terminal_growth_pct"] = {
        "value": _s(tg, 1),
        "source": "Assumption: long-run nominal growth; set your own",
    }
    defaults["years"] = {"value": "5", "source": "Assumption"}

    financial = (sector or "").strip().lower() in FINANCIAL
    return {
        "symbol": inst.symbol,
        "name": inst.name,
        "currency": ccy,
        "price": _s(price),
        "price_time": quote.value.market_time.isoformat() if quote.value is not None else None,
        "sector": sector,
        "dcf_applicable": not financial,
        "dcf_reason": None if not financial else NOT_FOR_FINANCIALS,
        "defaults": defaults,
        "labels": vm.LABELS,
        "cash_flow_definition": (
            "Free cash flow to equity ≈ operating cash flow − capital expenditure (as reported, after interest and "
            "tax); assumes no net new borrowing. Discounted at a cost of equity; no debt is subtracted."
        ),
        "notes": [
            "The statement currency is assumed to be the listing currency (the provider does not state it); if "
            "the company reports in another currency, convert the base cash flow before comparing with the price.",
        ],
        "hypothetical": HYPOTHETICAL,
    }


def _dec_out(x):
    if isinstance(x, Decimal):
        return _s(x, 4)
    if isinstance(x, dict):
        return {k: _dec_out(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_dec_out(v) for v in x]
    return x


def run_dcf(raw_inputs: dict, price: Decimal | None, rows_axis: str, cols_axis: str) -> dict:
    try:
        inp = vm.DcfInputs.parse(raw_inputs)
        out = vm.dcf(inp)
        sens = vm.sensitivity(inp, rows_axis, cols_axis)
    except vm.ValuationError as err:
        raise AppError(422, "invalid_assumption", err.message, {"field": err.field}) from err
    result = _dec_out(out)
    result["vs_price_pct"] = _s((out["per_share"] / price - 1) * 100, 2) if price and price > 0 else None
    return {
        "inputs": _dec_out(inp.__dict__),
        "result": result,
        "sensitivity": _dec_out(sens),
        "hypothetical": HYPOTHETICAL,
        "formula": vm.__doc__.split("Peer multiples")[0].strip(),
    }


async def multiples(db: Session, market: MarketDataService, symbol: str) -> dict:
    from marketdesk.services.screener import refresh_instruments, suggest_peers

    inst = await resolve_instrument(db, market, symbol)
    await refresh_instruments(db, market, [inst], hours=market.settings.screener_snapshot_hours, limit=1)
    ps = db.scalar(select(PeerSet).where(PeerSet.instrument_id == inst.id))
    if ps is not None:
        syms, source = list(ps.peers), "your peer group"
    else:
        fx = await valuation_rate(market, "USD", "INR")
        rates = {("USD", "INR"): fx["rate"]} if fx.get("rate") else {}
        syms, source = [p["symbol"] for p in suggest_peers(db, inst, market.source, rates)], "suggested peers"
    peers = [i for s in syms if (i := find_instrument(db, market.source, s)) is not None]
    await refresh_instruments(db, market, peers, hours=market.settings.screener_snapshot_hours, limit=5)
    snaps = {
        r.instrument_id: r.values
        for r in db.scalars(
            select(ScreenMetric).where(ScreenMetric.instrument_id.in_([inst.id, *[p.id for p in peers]]))
        )
    }
    own = snaps.get(inst.id) or {}

    def num(values: dict, key: str) -> Decimal | None:
        v = (values.get(key) or {}).get("v")
        return Decimal(v) if v is not None else None

    price = num(own, "last_price")
    pe, pb = num(own, "pe_ratio"), num(own, "price_to_book")
    eps = price / pe if price and pe and pe > 0 else None
    bvps = price / pb if price and pb and pb > 0 else None
    table = [
        {
            "symbol": p.symbol,
            "name": p.name,
            "pe_ratio": _s(num(snaps.get(p.id) or {}, "pe_ratio"), 2),
            "price_to_book": _s(num(snaps.get(p.id) or {}, "price_to_book"), 2),
            "as_of": ((snaps.get(p.id) or {}).get("pe_ratio") or {}).get("as_of"),
        }
        for p in peers
    ]
    ranges = {}
    for key, own_ps, label in (
        ("pe_ratio", eps, "P/E × own EPS"),
        ("price_to_book", bvps, "P/B × own book value per share"),
    ):
        r = vm.multiple_range([num(snaps.get(p.id) or {}, key) for p in peers], own_ps)
        ranges[key] = {"label": label, "own_per_share": _s(own_ps), **_dec_out(r)}
    return {
        "symbol": inst.symbol,
        "currency": inst.currency,
        "price": _s(price),
        "own": {"pe_ratio": _s(pe, 2), "price_to_book": _s(pb, 2)},
        "peer_source": source,
        "peers": table,
        "ranges": ranges,
        "method": "Implied price = a peer multiple × this company's own per-share figure (EPS = price ÷ own P/E; book "
        "value per share = price ÷ own P/B), at the peers' minimum, quartiles, median and maximum. Multiples come from "
        "the stored screening snapshots and are currency-neutral.",
        "hypothetical": HYPOTHETICAL,
    }


# --------------------------------------------------------------------- scenarios
CASES = ("bear", "base", "bull", "custom")


def scenario_dict(s: ValuationScenario) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "case": s.case,
        "inputs": s.inputs,
        "notes": s.notes,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def clean_inputs(raw: dict) -> dict:
    try:
        inp = vm.DcfInputs.parse(raw)
    except vm.ValuationError as err:
        raise AppError(422, "invalid_assumption", err.message, {"field": err.field}) from err
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in inp.__dict__.items()}


# --------------------------------------------------------------------- stress
async def stress(
    db: Session, market: MarketDataService, account: str, market_shocks: dict, symbol_shocks: dict, fx_shocks: dict
) -> dict:
    if account not in (*CURRENCIES, "ALL"):
        raise AppError(422, "bad_account", "Account is INR, USD or ALL.")
    ccys = list(CURRENCIES) if account == "ALL" else [account]
    base = "INR" if account == "ALL" else account
    holdings, cash, rates, unpriced = [], {}, {base: Decimal(1)}, []
    rate_info = {}
    for c in ccys:
        s = await portfolio_summary(db, market, c)
        if not s["has_transactions"]:
            continue
        if c != base:
            fx = await valuation_rate(market, c, base)
            rate_info[f"{c}/{base}"] = {
                "rate": _s(fx.get("rate")),
                "status": fx.get("status"),
                "market_time": fx.get("market_time").isoformat() if fx.get("market_time") else None,
            }
            if fx.get("rate") is None:
                raise AppError(422, "no_rate", f"No usable {c}/{base} rate to express the {c} account in {base}.")
            rates[c] = fx["rate"]
        cash[c] = s["cash"]
        insts = {
            i.symbol: i
            for i in db.scalars(select(Instrument).where(Instrument.symbol.in_([h["symbol"] for h in s["holdings"]])))
        }
        for h in s["holdings"]:
            if h["market_value"] is None:
                unpriced.append(h["symbol"])
                continue
            inst = insts.get(h["symbol"])
            holdings.append(vm.StressHolding(h["symbol"], c, market_of(inst) if inst else "Other", h["market_value"]))
    if not holdings and not any(cash.values()):
        return {"available": False, "reason": "No holdings or cash in this account yet."}

    def decs(d: dict, what: str) -> dict:
        out = {}
        for k, v in (d or {}).items():
            try:
                out[str(k).upper()] = Decimal(str(v))
            except Exception as err:
                raise AppError(422, "bad_shock", f"{what} shock for {k} must be a number.") from err
        return out

    try:
        out = vm.stress(
            holdings,
            cash,
            rates,
            base,
            decs(market_shocks, "Market"),
            decs(symbol_shocks, "Holding"),
            decs(fx_shocks, "Currency"),
        )
    except vm.ValuationError as err:
        raise AppError(422, "bad_shock", err.message, {"field": err.field}) from err
    res = _dec_out(out)
    return {
        "available": True,
        "account": account,
        **res,
        "unpriced": unpriced,
        "rates": rate_info,
        "markets": sorted({h.market for h in holdings}),
        "method": vm.__doc__.split("Portfolio stress")[1].strip(),
        "hypothetical": HYPOTHETICAL,
    }

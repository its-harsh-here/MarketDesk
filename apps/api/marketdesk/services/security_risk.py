"""Terminal T6: relative value and risk for one security.

Pure functions first (tested with hand vectors), then the builder that fetches prices, snapshots and peers.
Conventions: returns come from the provider's split-adjusted daily closes (dividends not included); beta and
correlation use daily returns when the security and benchmark trade in the same time zone and weekly (Friday) returns
otherwise; drawdowns are measured from the running high of closes. Liquidity is shown as traded volume and value and the
median daily high-low range; no bid-ask spread is shown because MarketDesk has no quotes to measure one (a spread
estimated from daily prices proved unreliable for liquid stocks).
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.models import Instrument, MarketCacheEntry, PeerSet, ScreenMetric
from marketdesk.providers.base import ProviderError
from marketdesk.services import risk_math as rm
from marketdesk.services import screener
from marketdesk.services.market import MarketDataService

log = logging.getLogger("marketdesk.risk")

WINDOWS = (("1Y", 365), ("3Y", 365 * 3))
DD_WINDOWS = (("1Y", 365), ("3Y", 365 * 3), ("5Y", 365 * 5))
Z_METRICS = (
    "pe_ratio",
    "price_to_book",
    "dividend_yield_pct",
    "revenue_growth_pct",
    "net_margin_pct",
    "roe_pct",
    "debt_to_equity",
    "volatility_1y_pct",
    "return_1y_pct",
)
SI_TTL = timedelta(hours=12)


# --------------------------------------------------------------------- pure
def _window(closes: dict[date, Decimal], end: date, days: int) -> dict[date, Decimal]:
    start = end - timedelta(days=days)
    return {d: v for d, v in closes.items() if d > start}


def sensitivity(a: dict[date, Decimal], b: dict[date, Decimal], same_market: bool) -> dict:
    """Beta, correlation and R² of the security's returns against the benchmark's on aligned dates."""
    if same_market:
        pairs, method, need = rm.aligned_daily_returns(a, b), "daily", rm.MIN_DAILY_PAIRS
    else:
        pairs, method, need = (
            rm.aligned_daily_returns(rm.weekly_closes(a), rm.weekly_closes(b)),
            "weekly",
            rm.MIN_WEEKLY_PAIRS,
        )
    n = len(pairs)
    if n < need:
        return {"beta": None, "correlation": None, "r2": None, "n": n, "method": method,
                "why": f"Only {n} aligned {method} returns; at least {need} are needed."}  # fmt: skip
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    cov = sum((x - mx) * (y - my) for x, y in pairs) / (n - 1)
    vx = sum((x - mx) ** 2 for x, _ in pairs) / (n - 1)
    vy = sum((y - my) ** 2 for _, y in pairs) / (n - 1)
    if vx == 0 or vy == 0:
        return {"beta": None, "correlation": None, "r2": None, "n": n, "method": method,
                "why": "One of the series did not move."}  # fmt: skip
    corr = cov / math.sqrt(vx * vy)
    return {"beta": cov / vy, "correlation": corr, "r2": corr * corr, "n": n, "method": method, "why": None}


def episodes(closes: list[tuple[date, float]], top: int = 3) -> list[dict]:
    """Drawdown episodes: from a high, through the lowest close, to the first close back at that high (or ongoing)."""
    out: list[dict] = []
    peak_v, peak_d = -math.inf, None
    cur: dict | None = None
    for d, v in closes:
        if v >= peak_v:
            if cur is not None:
                cur["recovered"] = d
                out.append(cur)
                cur = None
            peak_v, peak_d = v, d
            continue
        depth = v / peak_v - 1.0
        if cur is None:
            cur = {"peak": peak_d, "trough": d, "depth": depth, "recovered": None}
        elif depth < cur["depth"]:
            cur["trough"], cur["depth"] = d, depth
    if cur is not None:
        out.append(cur)
    out.sort(key=lambda e: e["depth"])
    for e in out:
        e["days_to_trough"] = (e["trough"] - e["peak"]).days
        e["days_to_recover"] = (e["recovered"] - e["trough"]).days if e["recovered"] else None
    return out[:top]


def drawdown_profile(closes: dict[date, Decimal]) -> dict:
    series = sorted((d, float(v)) for d, v in closes.items())
    if len(series) < 2:
        return {"why": "Not enough prices."}
    end = series[-1][0]
    windows = {}
    for label, days in DD_WINDOWS:
        part = [(d, v) for d, v in series if d > end - timedelta(days=days)]
        if not part or (part[0][0] - (end - timedelta(days=days))).days > 10:
            windows[label] = {"max": None, "why": f"History shorter than {label}."}
            continue
        dd = rm.drawdowns(part)
        windows[label] = {"max": dd["max"]["depth"], "peak": dd["max"]["peak"], "trough": dd["max"]["trough"],
                          "recovered": dd["max"]["recovered"]}  # fmt: skip
    high_d, high_v = max(series, key=lambda x: x[1])
    return {
        "current": series[-1][1] / max(v for _, v in series) - 1.0,
        "high": {"date": high_d, "close": high_v},
        "windows": windows,
        "episodes": episodes(series),
        "from": series[0][0],
        "to": end,
    }


def volatility(closes: dict[date, Decimal], end: date) -> dict:
    out = {}
    for label, days in WINDOWS:
        part = sorted(_window(closes, end, days).items())
        rets = [float(b / a) - 1.0 for (_, a), (_, b) in zip(part, part[1:], strict=False) if a > 0]
        v = rm.volatility(rets)
        out[label] = {"value": v, "n": len(rets), "why": None if v is not None else f"Only {len(rets)} returns."}
    return out


def daily_range(bars: list) -> float | None:
    """Median of (high − low) ÷ close over the sessions given, as a fraction. A plain measure of how far the price
    typically moves within a day; it is not a bid-ask spread (MarketDesk has no quotes to measure one)."""
    r = sorted(float((b.high - b.low) / b.close) for b in bars
               if b.close and b.high is not None and b.low is not None and b.close > 0)  # fmt: skip
    return statistics.median(r) if len(r) >= 20 else None


def liquidity(bars: list) -> dict:
    with_vol = [b for b in bars if b.volume is not None]
    out: dict = {}
    for n in (20, 60):
        last = with_vol[-n:]
        out[f"adv_{n}"] = (sum(Decimal(b.volume) for b in last) / len(last)) if len(last) == n else None
    last20 = with_vol[-20:]
    out["value_20"] = sum(Decimal(b.volume) * b.close for b in last20) / len(last20) if len(last20) == 20 else None
    rng = daily_range(bars[-60:])
    out["median_range_pct"] = None if rng is None else rng * 100
    out["sessions"] = len(bars[-60:])
    return out


def zscores(target: dict, universe: list[dict], keys=Z_METRICS) -> list[dict]:
    """Where the security sits within the universe on each metric: z = (value − mean) ÷ standard deviation (sample),
    and the share of members at or below its value. Members without the metric are left out of that metric."""
    rows = []
    for k in keys:
        v = (target.get(k) or {}).get("v")
        vals = [Decimal(m[k]["v"]) for m in universe if (m.get(k) or {}).get("v") is not None]
        row: dict = {"key": k, "value": v, "n": len(vals)}
        if v is None:
            row["why"] = (target.get(k) or {}).get("why") or "No value for this security."
        elif len(vals) < 5:
            row["why"] = f"Only {len(vals)} members have this metric; at least 5 are needed."
        else:
            x = Decimal(v)
            mean = sum(vals) / len(vals)
            sd = Decimal(str(statistics.stdev(float(t) for t in vals)))
            row.update(
                mean=mean,
                median=Decimal(str(statistics.median(float(t) for t in vals))),
                z=None if sd == 0 else (x - mean) / sd,
                percentile=Decimal(sum(1 for t in vals if t <= x)) / len(vals) * 100,
                why=None,
            )
        rows.append(row)
    return rows


def short_interest_rows(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        out.append(
            {
                "settlement_date": r.get("settlementDate"),
                "short_position": r.get("currentShortPositionQuantity"),
                "previous": r.get("previousShortPositionQuantity"),
                "change_pct": r.get("changePercent"),
                "avg_daily_volume": r.get("averageDailyVolumeQuantity"),
                "days_to_cover": r.get("daysToCoverQuantity"),
                "market": r.get("marketClassCode"),
                "split": r.get("stockSplitFlag") == "S",
                "revised": r.get("revisionFlag") == "R",
            }
        )
    return out


# --------------------------------------------------------------------- builder
def _default_benchmark(settings, market: MarketDataService, inst: Instrument) -> str:
    from marketdesk.api.routes_market import benchmark_symbols

    if inst.country == "US" and market.source == "yahoo":
        return "^GSPC"
    return benchmark_symbols(settings, market)[0]


async def _closes(market: MarketDataService, symbol: str):
    h = await market.history(symbol, "5Y")
    if h.value is None or not h.value.bars:
        return None, [], h
    return {b.session_date: b.close for b in h.value.bars if b.close is not None}, list(h.value.bars), h


def _short_interest(db: Session, finra, inst: Instrument) -> dict:
    base = {"source": "FINRA consolidated short interest", "attribution": "FINRA"}
    if inst.country != "US":
        return {**base, "status": "not_applicable", "reason": "FINRA short interest covers US-traded securities."}
    if finra is None or not finra.enabled:
        return {**base, "status": "not_configured", "reason": finra.problem if finra else "Not configured."}
    symbol = inst.symbol.replace("-", ".")
    key = f"finra:si:{symbol}"
    row = db.get(MarketCacheEntry, key)
    now = datetime.now(UTC)
    fetched = row.fetched_at if row is not None else None
    if fetched is not None and fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    if row is None or fetched is None or now - fetched > SI_TTL:
        try:
            raw = finra.short_interest(symbol)
        except ProviderError as err:
            if row is None:
                return {**base, "status": "unavailable", "reason": f"FINRA: {err.message}"}
            raw, status = row.payload, "stale"
        except Exception as exc:  # noqa: BLE001 - a FINRA surprise must never take the whole risk view down
            log.warning("finra short interest failed: %s", type(exc).__name__)
            if row is None:
                return {**base, "status": "unavailable", "reason": f"FINRA request failed ({type(exc).__name__})."}
            raw, status = row.payload, "stale"
        else:
            entry = row or MarketCacheEntry(key=key, kind="finra_short_interest", provider="finra")
            entry.payload, entry.fetched_at, entry.last_access_at = raw, now, now
            db.merge(entry)
            db.commit()
            fetched, status = now, "available"
    else:
        raw, status = row.payload, "cached"
    rows = short_interest_rows(raw or [])
    return {
        **base,
        "status": status if rows else "missing",
        "reason": None if rows else "FINRA has no short-interest records for this symbol in the last year.",
        "fetched_at": fetched,
        "rows": rows[:12],
        "note": "Short positions reported by broker-dealers twice a month; days to cover = short position ÷ average "
        "daily volume, as published by FINRA.",
    }


async def _peer_bands(db: Session, market: MarketDataService, research, inst: Instrument, settings) -> dict:
    from marketdesk.services.financial_view import ANNUAL_PERIODS, _bands

    ps = db.scalar(select(PeerSet).where(PeerSet.instrument_id == inst.id))
    if ps is not None:
        symbols, source = list(ps.peers), "saved"
    else:
        symbols, source = [p["symbol"] for p in screener.suggest_peers(db, inst, market.source, {}, 5)], "suggested"
    rows = []
    for sym in [inst.symbol, *symbols][:6]:
        other = db.scalar(select(Instrument).where(Instrument.provider == market.source, Instrument.symbol == sym))
        if other is None:
            continue
        if other.country != "US" or research is None or not research.client.enabled:
            rows.append({"symbol": sym, "why": "P/E history needs SEC filings (US registrants)."})
            continue
        env = await asyncio.to_thread(research.financials, db, other, "annual", None, None, None, ANNUAL_PERIODS)
        st = env.get("data")
        if not st or not st.get("period_ends"):
            rows.append({"symbol": sym, "why": env.get("reason") or "No annual SEC statements."})
            continue
        b = await _bands(market, other, st)
        pe = b.get("pe") or {}
        rows.append({"symbol": sym, **{k: pe.get(k) for k in ("n", "min", "median", "max", "current", "percentile")},
                     "why": pe.get("why") or b.get("reason")})  # fmt: skip
    return {"source": source, "rows": rows}


async def build(
    db: Session,
    market: MarketDataService,
    research,
    finra,
    settings,
    inst: Instrument,
    benchmark: str | None,
    universe: dict | None,
) -> dict:
    bench_sym = benchmark or _default_benchmark(settings, market, inst)
    (closes, bars, hist), (bcloses, _, bhist) = await asyncio.gather(_closes(market, inst.symbol),
                                                                    _closes(market, bench_sym))  # fmt: skip
    out: dict = {"symbol": inst.symbol, "benchmark": {"symbol": bench_sym}}
    if closes is None:
        return {**out, "status": "missing", "reason": hist.meta.message or "No daily prices."}
    end = max(closes)
    out["prices"] = {"source": f"{market.source} daily closes", "adjustment": hist.value.adjustment, "to": end}
    # benchmark sensitivity
    if bcloses is None:
        out["sensitivity"] = {"why": bhist.meta.message or f"No prices for {bench_sym}."}
    else:
        bref = bhist.value.instrument
        same = bool(inst.timezone and bref.timezone and inst.timezone == bref.timezone)
        out["benchmark"].update(name=bref.name, timezone=bref.timezone, same_market=same)
        out["sensitivity"] = {
            label: sensitivity(_window(closes, end, days), _window(bcloses, end, days), same) for label, days in WINDOWS
        }
    out["volatility"] = volatility(closes, end)
    out["drawdowns"] = drawdown_profile(closes)
    out["liquidity"] = liquidity(bars)
    # relative to the universe (stored snapshots only; refresh happens on the Screener page)
    target = db.get(ScreenMetric, inst.id)
    if (
        target is None
        or target.provider != market.source
        or screener.is_stale(target, settings.screener_snapshot_hours)
    ):
        target = await screener.build_snapshot(db, market, inst)
    uni = screener.resolve_universe(db, market.source, universe or {"kind": "watchlists"}, 500)
    members = [m for m in uni["instruments"] if m.id != inst.id]
    snaps = {s.instrument_id: s for s in db.scalars(select(ScreenMetric).where(
        ScreenMetric.instrument_id.in_([m.id for m in members]), ScreenMetric.provider == market.source))}  # fmt: skip
    vals = [s.values for s in snaps.values()]
    catalog = {m.key: m for m in screener.METRICS}
    out["relative"] = {
        "universe": {"label": uni["label"], "members": len(members), "with_snapshot": len(vals)},
        "rows": [
            {**r, "label": catalog[r["key"]].label, "unit": catalog[r["key"]].unit}
            for r in zscores(target.values, vals)
        ],  # fmt: skip
        "note": "Members are compared on their stored snapshots (refresh them on the Screener page); the security "
        "itself is not counted among the members.",
    }
    out["peer_valuation"] = await _peer_bands(db, market, research, inst, settings)
    out["short_interest"] = _short_interest(db, finra, inst)
    return out


def jsonable(x):
    """Decimals as strings, floats rounded, dates as ISO strings."""
    if isinstance(x, Decimal):
        return format(x.quantize(Decimal("0.0001")), "f")
    if isinstance(x, float):
        return None if math.isnan(x) or math.isinf(x) else round(x, 6)
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    return x

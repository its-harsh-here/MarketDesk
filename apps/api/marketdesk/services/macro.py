"""Macro and sector context (M12).

Only market-traded series the configured provider supplies are used (Yahoo via yfinance in production; the sample
dataset in fixture mode). Each series states its provider, frequency, observation date and revision status (market
prices are not revised). Official statistics (inflation, employment) and their release calendars need a verified
source with a key and licence (e.g. FRED for US series, RBI/MOSPI for India); they are listed as not configured rather
than approximated. Correlations are descriptive, never causal.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Instrument, MacroLink, ScreenMetric
from marketdesk.services import risk_math as rm
from marketdesk.services.market import MarketDataService

USABLE = {"sample", "available", "cached", "stale"}


@dataclass(frozen=True)
class Series:
    symbol: str
    name: str
    group: str
    unit: str
    kind: str  # level | yield (changes in percentage points)


YAHOO_SERIES = (
    Series("^NSEI", "Nifty 50", "Benchmarks", "index points", "level"),
    Series("^BSESN", "S&P BSE Sensex", "Benchmarks", "index points", "level"),
    Series("^GSPC", "S&P 500", "Benchmarks", "index points", "level"),
    Series("^IXIC", "Nasdaq Composite", "Benchmarks", "index points", "level"),
    Series("^INDIAVIX", "India VIX", "Volatility", "index points", "level"),
    Series("^VIX", "CBOE VIX", "Volatility", "index points", "level"),
    Series("^TNX", "US 10-year Treasury yield", "Rates", "% a year", "yield"),
    Series("^IRX", "US 13-week Treasury bill yield", "Rates", "% a year", "yield"),
    Series("USDINR=X", "US dollar in rupees", "FX", "INR per USD", "level"),
    Series("EURINR=X", "Euro in rupees", "FX", "INR per EUR", "level"),
    Series("DX-Y.NYB", "US dollar index", "FX", "index points", "level"),
    Series("BZ=F", "Brent crude (front-month future)", "Commodities", "USD per barrel", "level"),
    Series("CL=F", "WTI crude (front-month future)", "Commodities", "USD per barrel", "level"),
    Series("GC=F", "Gold (front-month future)", "Commodities", "USD per troy ounce", "level"),
    Series("HG=F", "Copper (front-month future)", "Commodities", "USD per pound", "level"),
)
FIXTURE_SERIES = (
    Series("SX:SX50", "SampleX Composite Index", "Benchmarks", "index points", "level"),
    Series("SX:SXFIN", "SampleX Financials Index", "Benchmarks", "index points", "level"),
    Series("SX:USDINR", "Sample USD/INR rate", "FX", "INR per USD", "level"),
)
WINDOWS = (
    ("1w", timedelta(days=7)),
    ("1m", relativedelta(months=1)),
    ("3m", relativedelta(months=3)),
    ("1y", relativedelta(years=1)),
)
NOT_CONFIGURED = [
    {
        "name": "Official statistics (US CPI, unemployment, policy rates) and release dates",
        "source": "FRED (Federal Reserve Bank of St. Louis) — free API key, attribution required",
        "status": "not configured",
        "why": "Needs a FRED API key; release and revision (vintage) dates come with it.",
    },
    {
        "name": "Indian official statistics (CPI, IIP, GDP, RBI policy rate) and release calendar",
        "source": "RBI / MOSPI publications",
        "status": "not verified",
        "why": "No machine-readable source with confirmed terms has been verified yet.",
    },
]


def series_list(market: MarketDataService) -> tuple[Series, ...]:
    return FIXTURE_SERIES if market.source == "fixture" else YAHOO_SERIES


def _change(kind: str, last: Decimal, then: Decimal) -> dict:
    if kind == "yield":
        return {"value": format((last - then).quantize(Decimal("0.01")), "f"), "unit": "pp"}
    if then == 0:
        return {"value": None, "unit": "%"}
    return {"value": format(((last / then - 1) * 100).quantize(Decimal("0.01")), "f"), "unit": "%"}


def series_row(s: Series, hist_bars: list, quote, meta_status: str, meta: dict) -> dict:
    bars = hist_bars
    row = {
        "symbol": s.symbol,
        "name": s.name,
        "group": s.group,
        "unit": s.unit,
        "kind": s.kind,
        "frequency": "daily (trading days)",
        "revision": "Market price: not revised",
        **meta,
    }
    if not bars:
        return {**row, "value": None, "changes": {}, "spark": []}
    last = bars[-1]
    out = {}
    for key, delta in WINDOWS:
        target = last.session_date - delta
        prior = [b for b in bars if b.session_date <= target]
        start = prior[-1] if prior else (bars[0] if bars[0].session_date <= target + timedelta(days=5) else None)
        out[key] = (
            {**_change(s.kind, last.close, start.close), "from": start.session_date.isoformat()} if start else None
        )
    value = quote.last_price if quote is not None else last.close
    obs = quote.market_time.isoformat() if quote is not None else last.session_date.isoformat()
    day = _change(s.kind, value, quote.previous_close) if quote is not None and quote.previous_close else None
    return {
        **row,
        "value": format(value, "f"),
        "observed": obs,
        "session_date": last.session_date.isoformat(),
        "change_1d": day,
        "changes": out,
        "spark": [[b.session_date.isoformat(), format(b.close, "f")] for b in bars[-60:]],
        "status": meta_status,
    }


async def watchboard(market: MarketDataService) -> dict:
    series = series_list(market)
    quotes, hists = await asyncio.gather(
        asyncio.gather(*(market.quote(s.symbol) for s in series)),
        asyncio.gather(*(market.history(s.symbol, "1Y") for s in series)),
    )
    rows = []
    for s, q, h in zip(series, quotes, hists, strict=True):
        usable_h = h.value is not None and h.meta.status in USABLE
        usable_q = q.value is not None and q.meta.status in USABLE
        meta = {
            "provider": market.source,
            "fetched_at": (q.meta.fetched_at or h.meta.fetched_at).isoformat()
            if (q.meta.fetched_at or h.meta.fetched_at)
            else None,
            "message": None if usable_h else (h.meta.message or f"History {h.meta.status}"),
        }
        rows.append(
            series_row(
                s,
                h.value.bars if usable_h else [],
                q.value if usable_q else None,
                q.meta.status if usable_q else h.meta.status,
                meta,
            )
        )
    return {
        "series": rows,
        "not_configured": NOT_CONFIGURED,
        "provider": market.source,
        "note": "Market-traded series from the configured provider. Futures are front-month contracts (they roll); "
        "yields are shown in percentage points. Official statistics are not approximated from markets.",
    }


def briefing(board: dict, links: list[dict], window: str = "1w") -> dict:
    """Deterministic: the largest moves over the window, each with its value, date and source, plus the companies
    the owner linked to those series (their own notes). No causes are inferred."""
    moves = []
    for s in board["series"]:
        ch = (s.get("changes") or {}).get(window)
        if not ch or ch.get("value") is None:
            continue
        size = abs(Decimal(ch["value"])) * (Decimal(10) if ch["unit"] == "pp" else Decimal(1))  # 0.1 pp ≈ 1%
        moves.append((size, s, ch))
    moves.sort(key=lambda m: -m[0])
    items = []
    for _, s, ch in moves[:6]:
        sign = "+" if Decimal(ch["value"]) > 0 else ""
        text = (
            f"{s['name']}: {sign}{ch['value']}{' pp' if ch['unit'] == 'pp' else '%'} since {ch['from']} to "
            f"{s['value']} {s['unit']} (as of {s['session_date']}; {s['provider']})."
        )
        related = [lk for lk in links if lk["series_symbol"] == s["symbol"]]
        items.append(
            {
                "series": s["symbol"],
                "text": text,
                "linked": [
                    {
                        "symbol": lk["symbol"],
                        "relation": lk["relation"],
                        "direction": lk["direction"],
                        "note": lk["note"],
                    }
                    for lk in related
                ],
            }
        )
    return {
        "window": window,
        "items": items,
        "note": "Largest moves first (0.1 percentage point of yield counted like 1%). Linked companies and notes "
        "are your own entries; nothing here states a cause or an effect.",
    }


# --------------------------------------------------------------------- sector-relative
def sector_relative(
    db: Session, provider: str, insts: list[Instrument], metric: str, bench: dict[str, Decimal | None]
) -> dict:
    """Each member's return minus its sector's equal-weighted average (within these members) and minus its market's
    benchmark over the same window."""
    if metric not in ("return_1m_pct", "return_3m_pct", "return_1y_pct"):
        raise AppError(422, "bad_metric", "Choose the 1-month, 3-month or 1-year return.")
    snaps = {
        r.instrument_id: r.values
        for r in db.scalars(
            select(ScreenMetric).where(
                ScreenMetric.instrument_id.in_([i.id for i in insts]), ScreenMetric.provider == provider
            )
        )
    }
    vals = []
    for i in insts:
        v = (snaps.get(i.id) or {}).get(metric) or {}
        sector = (snaps.get(i.id) or {}).get("sector") or "Sector not reported"
        vals.append((i, sector, Decimal(v["v"]) if v.get("v") is not None else None, v.get("why")))
    by_sector: dict[str, list[Decimal]] = {}
    for _, sector, v, _ in vals:
        if v is not None:
            by_sector.setdefault(sector, []).append(v)
    rows = []
    for i, sector, v, why in vals:
        peers = by_sector.get(sector, [])
        avg = sum(peers) / len(peers) if peers else None
        market = (
            "IN"
            if (i.country == "IN" or i.timezone == "Asia/Kolkata")
            else "US"
            if (i.country == "US" or i.timezone == "America/New_York")
            else None
        )
        b = bench.get(market) if market else None
        rows.append(
            {
                "symbol": i.symbol,
                "name": i.name,
                "sector": sector,
                "return_pct": None if v is None else format(v, "f"),
                "why": why if v is None else None,
                "sector_avg_pct": None if avg is None else format(avg.quantize(Decimal("0.01")), "f"),
                "sector_n": len(peers),
                "vs_sector_pp": None
                if v is None or avg is None or len(peers) < 2
                else format((v - avg).quantize(Decimal("0.01")), "f"),
                "benchmark_pct": None if b is None else format(b, "f"),
                "vs_benchmark_pp": None if v is None or b is None else format((v - b).quantize(Decimal("0.01")), "f"),
            }
        )
    rows.sort(key=lambda r: (r["vs_sector_pp"] is None, -Decimal(r["vs_sector_pp"] or 0)))
    return {
        "metric": metric,
        "rows": rows,
        "method": "Sector average = equal-weighted mean of the same return across members of that sector in this "
        "universe (shown only with two or more members). Benchmark = the market's index return over the same "
        "window. Price returns only; dividends excluded.",
    }


# --------------------------------------------------------------------- exposure map
def link_dict(lk: MacroLink, inst: Instrument) -> dict:
    return {
        "id": lk.id,
        "symbol": inst.symbol,
        "name": inst.name,
        "series_symbol": lk.series_symbol,
        "relation": lk.relation,
        "direction": lk.direction,
        "note": lk.note,
    }


async def link_correlation(market: MarketDataService, inst: Instrument, series_symbol: str) -> dict:
    a, b = await asyncio.gather(market.history(inst.symbol, "1Y"), market.history(series_symbol, "1Y"))
    if a.value is None or b.value is None:
        return {"r": None, "n": 0, "method": None, "why": "One-year history unavailable for one of the two."}
    ca = {x.session_date: x.close for x in a.value.bars}
    cb = {x.session_date: x.close for x in b.value.bars}
    same = (a.value.instrument.timezone or "x") == (b.value.instrument.timezone or "y")
    c = rm.correlation(ca, cb, same)
    return {**c, "r": None if c["r"] is None else f"{c['r']:.2f}"}


def benchmark_returns(board: dict, metric: str) -> dict[str, Decimal | None]:
    key = {"return_1m_pct": "1m", "return_3m_pct": "3m", "return_1y_pct": "1y"}[metric]
    pick = {"IN": ("^NSEI", "SX:SX50"), "US": ("^GSPC",)}
    out: dict[str, Decimal | None] = {}
    for market, syms in pick.items():
        row = next((s for s in board["series"] if s["symbol"] in syms), None)
        ch = (row or {}).get("changes", {}).get(key) if row else None
        out[market] = Decimal(ch["value"]) if ch and ch.get("value") is not None else None
    return out


_ = date  # dates arrive as ISO strings from the market service

"""Screener and peers (M06): a declared, bounded universe screened from a normalized snapshot.

- Universe: one watchlist, all watchlists, current holdings, or a custom list the owner pasted (bounded). Never "the
  whole market": every result names its universe and how many of its members have data.
- Snapshot: one ``ScreenMetric`` row per instrument holding every metric's value (or null with the reason), plus where
  each input came from and when. Screens, peers and the heatmap read only snapshots; refreshing them is a separate,
  bounded job that goes through the cached market-data service.
- Missing values never pass a filter and are never treated as zero; each filter reports how many members it could not
  evaluate.
"""

from __future__ import annotations

import asyncio
import csv
import io
import math
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Instrument, PeerSet, SavedScreen, ScreenMetric, ScreenUniverse, Watchlist, WatchlistItem
from marketdesk.services.csv_io import safe_cell
from marketdesk.services.instruments import find_instrument
from marketdesk.services.market import MarketDataService, Result

USABLE = {"sample", "available", "cached", "stale"}
EXCLUDED_KINDS = {"INDEX", "CURRENCY"}
FINANCIAL_SECTORS = {"financial services", "financial", "financials"}
SNAPSHOT_VERSION = 1


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    group: str
    unit: str  # currency | percent | multiple | shares
    source: str  # quote | history | fundamentals | statements
    formula: str


METRICS: tuple[Metric, ...] = (
    Metric("last_price", "Last price", "Price", "currency", "quote", "Last observed price from the quote."),
    Metric(
        "change_1d_pct", "1-day change", "Price", "percent", "quote", "(Last price − previous close) ÷ previous close."
    ),
    *(
        Metric(
            f"return_{n}_pct",
            f"{label} return",
            "Price",
            "percent",
            "history",
            f"Change from the last close on or before {label.lower()} before the latest bar (or the first close within "
            "5 days after it) to the latest close. Price only; dividends excluded.",
        )
        for n, label in (("1m", "1 month"), ("3m", "3 months"), ("6m", "6 months"), ("1y", "1 year"))
    ),
    Metric(
        "from_52w_high_pct",
        "From 52-week high",
        "Price",
        "percent",
        "history",
        "Latest close ÷ highest price of the last 52 weeks − 1 (0 means at the high).",
    ),
    Metric(
        "avg_volume_20d",
        "Avg volume (20 sessions)",
        "Liquidity",
        "shares",
        "history",
        "Mean volume of the 20 completed sessions before the latest bar (the latest may be incomplete).",
    ),
    Metric(
        "avg_value_20d",
        "Avg traded value (20 sessions)",
        "Liquidity",
        "currency",
        "history",
        "Mean of close × volume over the same 20 sessions, in the listing currency.",
    ),
    Metric("market_cap", "Market cap", "Valuation", "currency", "fundamentals", "As reported by the provider."),
    Metric(
        "pe_ratio",
        "P/E (trailing)",
        "Valuation",
        "multiple",
        "fundamentals",
        "Price ÷ trailing twelve-month earnings per share, as reported by the provider; "
        "none when earnings are negative.",
    ),
    Metric("price_to_book", "Price / book", "Valuation", "multiple", "fundamentals", "As reported by the provider."),
    Metric(
        "dividend_yield_pct",
        "Dividend yield",
        "Valuation",
        "percent",
        "fundamentals",
        "Dividends of the last 12 months ÷ price, as reported or derived by the provider.",
    ),
    Metric(
        "revenue_growth_pct",
        "Revenue growth (FY)",
        "Growth & profitability",
        "percent",
        "statements",
        "Latest fiscal-year revenue ÷ prior fiscal-year revenue − 1.",
    ),
    Metric(
        "net_margin_pct",
        "Net margin (FY)",
        "Growth & profitability",
        "percent",
        "statements",
        "Net income ÷ revenue for the latest fiscal year.",
    ),
    Metric(
        "roe_pct",
        "Return on equity (FY)",
        "Growth & profitability",
        "percent",
        "statements",
        "Net income ÷ shareholders' equity at the fiscal year end (ending, not average, equity).",
    ),
    Metric(
        "debt_to_equity",
        "Debt / equity",
        "Leverage",
        "multiple",
        "statements",
        "Total debt ÷ shareholders' equity at the latest fiscal year end. Not meaningful for banks and lenders.",
    ),
    Metric(
        "volatility_1y_pct",
        "Volatility (1Y)",
        "Risk",
        "percent",
        "history",
        "Sample standard deviation of daily log returns over up to 252 sessions × √252 (annualized).",
    ),
)
BY_KEY = {m.key: m for m in METRICS}
TEXT_FIELDS = {
    "country": "Market",
    "currency": "Currency",
    "sector": "Sector",
    "industry": "Industry",
    "exchange": "Exchange",
}
HEATMAP_METRICS = ("change_1d_pct", "return_1m_pct", "return_3m_pct", "return_1y_pct")
DEFAULT_COLUMNS = ("last_price", "change_1d_pct", "market_cap", "pe_ratio", "return_1y_pct")


def metric_catalog() -> dict:
    return {
        "metrics": [asdict(m) for m in METRICS],
        "text_fields": [{"key": k, "label": v} for k, v in TEXT_FIELDS.items()],
        "heatmap_metrics": list(HEATMAP_METRICS),
        "default_columns": list(DEFAULT_COLUMNS),
    }


# --------------------------------------------------------------------- snapshot computation
def _s(d: Decimal | float | None, places: int = 4) -> str | None:
    if d is None:
        return None
    if isinstance(d, float):
        if math.isnan(d) or math.isinf(d):
            return None
        d = Decimal(repr(d))
    return format(d.quantize(Decimal(10) ** -places), "f")


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, (date, datetime)) else None


def _val(v: Decimal | float | None, as_of: Any = None, places: int = 4, **extra) -> dict:
    return {"v": _s(v, places), "as_of": _iso(as_of), **extra}


def _none(why: str, as_of: Any = None) -> dict:
    return {"v": None, "why": why, "as_of": _iso(as_of)}


def _input_meta(r: Result | None) -> dict:
    if r is None:
        return {"status": "not_requested"}
    m = r.meta
    return {
        "status": m.status,
        "source": m.source,
        "fetched_at": _iso(m.fetched_at),
        "message": m.message if (m.status not in ("available", "cached", "sample") or r.value is None) else None,
    }


def _usable(r: Result | None) -> bool:
    return r is not None and r.value is not None and r.meta.status in USABLE


def _why(r: Result | None, what: str) -> str:
    if r is None:
        return f"{what} not requested."
    if r.meta.status == "unsupported":
        return f"{what} not supported for this instrument."
    if r.meta.status == "missing":
        return r.meta.message or f"The provider has no {what.lower()} for this instrument."
    return r.meta.message or f"{what} unavailable from the provider."


def _change_since(bars, months: int) -> dict:
    latest = bars[-1]
    target = latest.session_date - relativedelta(months=months)
    before = [b for b in bars if b.session_date <= target]
    if before:
        start = before[-1]
    else:
        start = bars[0]
        if start.session_date > target + timedelta(days=5):
            return _none(
                f"Price history starts {start.session_date.isoformat()}, after {target.isoformat()}.",
                latest.session_date,
            )
    if start.close <= 0:
        return _none("Starting close is not positive.", latest.session_date)
    return _val(
        (latest.close / start.close - 1) * 100, latest.session_date, 2, **{"from": start.session_date.isoformat()}
    )


def compute_snapshot(
    kind: str | None,
    quote: Result | None,
    history: Result | None,
    fundamentals: Result | None,
    statements: Result | None,
) -> dict:
    """Pure: every metric's value (string decimal) or null with a reason, plus text fields and input provenance."""
    out: dict[str, Any] = {}
    not_applicable = (kind or "").upper() in EXCLUDED_KINDS

    # quote
    if _usable(quote):
        q = quote.value  # type: ignore[union-attr]
        out["last_price"] = _val(q.last_price, q.market_time, 4)
        cp = q.change_percent
        out["change_1d_pct"] = (
            _val(cp, q.market_time, 2) if cp is not None else _none("No previous close.", q.market_time)
        )
    else:
        for k in ("last_price", "change_1d_pct"):
            out[k] = _none(_why(quote, "Quote"))

    # history
    bars = list(history.value.bars) if _usable(history) else []  # type: ignore[union-attr]
    if bars:
        last = bars[-1]
        for n, months in (("1m", 1), ("3m", 3), ("6m", 6), ("1y", 12)):
            out[f"return_{n}_pct"] = _change_since(bars, months)
        year = [b for b in bars if b.session_date > last.session_date - timedelta(days=365)]
        high = max((b.high or b.close) for b in year)
        out["from_52w_high_pct"] = _val((last.close / high - 1) * 100, last.session_date, 2)
        window = bars[-21:-1]
        vols = [(b.volume, b.close) for b in window if b.volume is not None]
        if len(window) >= 15 and len(vols) >= 15:
            out["avg_volume_20d"] = _val(Decimal(sum(v for v, _ in vols)) / len(vols), window[-1].session_date, 0)
            out["avg_value_20d"] = _val(sum(Decimal(v) * c for v, c in vols) / len(vols), window[-1].session_date, 0)
        else:
            why = "Volume is not reported for this instrument." if not vols else "Fewer than 15 sessions with volume."
            out["avg_volume_20d"] = out["avg_value_20d"] = _none(why, last.session_date)
        rets = [
            math.log(float(b.close) / float(a.close))
            for a, b in zip(bars[-253:-1], bars[-252:], strict=False)
            if a.close > 0
        ]
        if len(rets) >= 120:
            mean = sum(rets) / len(rets)
            sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
            out["volatility_1y_pct"] = _val(sd * math.sqrt(252) * 100, last.session_date, 2, n=len(rets))
        else:
            out["volatility_1y_pct"] = _none(
                f"Only {len(rets)} daily returns; at least 120 are needed.", last.session_date
            )
    else:
        why = _why(history, "Price history")
        for k in (
            "return_1m_pct",
            "return_3m_pct",
            "return_6m_pct",
            "return_1y_pct",
            "from_52w_high_pct",
            "avg_volume_20d",
            "avg_value_20d",
            "volatility_1y_pct",
        ):
            out[k] = _none(why)

    # fundamentals
    sector = industry = None
    if _usable(fundamentals):
        f = fundamentals.value  # type: ignore[union-attr]
        sector, industry = f.sector, f.industry
        fetched = fundamentals.meta.fetched_at  # type: ignore[union-attr]
        pairs = (
            ("market_cap", f.market_cap, 0),
            ("pe_ratio", f.pe_ratio, 2),
            ("price_to_book", f.price_to_book, 2),
            ("dividend_yield_pct", f.dividend_yield_percent, 2),
        )
        for key, v, places in pairs:
            if not_applicable:
                out[key] = _none("Not applicable to an index or currency.")
            elif v is None:
                why = {
                    "pe_ratio": "Not reported (earnings may be negative, or coverage is missing).",
                    "dividend_yield_pct": "No dividends reported for the last 12 months.",
                }.get(key, "Not reported by the provider.")
                out[key] = _none(why, fetched)
            else:
                out[key] = _val(v, fetched, places)
    else:
        why = "Not applicable to an index or currency." if not_applicable else _why(fundamentals, "Fundamentals")
        for k in ("market_cap", "pe_ratio", "price_to_book", "dividend_yield_pct"):
            out[k] = _none(why)

    # annual statements (ratios only: the statement currency may differ from the listing currency)
    financial = (sector or "").strip().lower() in FINANCIAL_SECTORS
    if _usable(statements):
        periods = statements.value.periods  # type: ignore[union-attr]
        p0 = periods[0]
        p1 = next((p for p in periods[1:] if 300 <= (p0.period_end - p.period_end).days <= 430), None)
        if p1 and p0.revenue and p1.revenue and p0.revenue > 0 and p1.revenue > 0:
            out["revenue_growth_pct"] = _val(
                (p0.revenue / p1.revenue - 1) * 100, p0.period_end, 2, **{"from": p1.period_end.isoformat()}
            )
        else:
            out["revenue_growth_pct"] = _none(
                "No prior fiscal year to compare."
                if p1 is None
                else "Revenue missing or not positive in one of the years.",
                p0.period_end,
            )
        if p0.revenue and p0.revenue > 0 and p0.net_income is not None:
            out["net_margin_pct"] = _val(p0.net_income / p0.revenue * 100, p0.period_end, 2)
        else:
            out["net_margin_pct"] = _none("Revenue or net income not reported.", p0.period_end)
        eq = p0.total_equity
        if eq is None:
            out["roe_pct"] = _none("Shareholders' equity not reported.", p0.period_end)
        elif eq <= 0:
            out["roe_pct"] = _none("Equity is zero or negative, so the ratio is not meaningful.", p0.period_end)
        elif p0.net_income is None:
            out["roe_pct"] = _none("Net income not reported.", p0.period_end)
        else:
            out["roe_pct"] = _val(p0.net_income / eq * 100, p0.period_end, 2)
        if financial:
            out["debt_to_equity"] = _none(
                "Not meaningful for banks and lenders: borrowing is their operating funding.", p0.period_end
            )
        elif eq is None or eq <= 0:
            out["debt_to_equity"] = _none("Equity not reported, zero or negative.", p0.period_end)
        elif p0.total_debt is None:
            out["debt_to_equity"] = _none("Total debt not reported.", p0.period_end)
        else:
            out["debt_to_equity"] = _val(p0.total_debt / eq, p0.period_end, 2)
    else:
        why = "Not applicable to an index or currency." if not_applicable else _why(statements, "Annual statements")
        for k in ("revenue_growth_pct", "net_margin_pct", "roe_pct", "debt_to_equity"):
            out[k] = _none(why)

    out["sector"] = sector
    out["industry"] = industry
    out["_inputs"] = {
        "quote": _input_meta(quote),
        "history": {**_input_meta(history), "adjustment": history.value.adjustment if _usable(history) else None},  # type: ignore[union-attr]
        "fundamentals": _input_meta(fundamentals),
        "statements": {
            **_input_meta(statements),
            "source_label": statements.value.source if _usable(statements) else None,  # type: ignore[union-attr]
        },
    }
    out["_version"] = SNAPSHOT_VERSION
    return out


async def build_snapshot(db: Session, market: MarketDataService, inst: Instrument) -> ScreenMetric:
    """Fetch the inputs through the cached market service and store the instrument's snapshot."""
    sym = inst.symbol
    excluded = (inst.kind or "").upper() in EXCLUDED_KINDS
    quote, history = await asyncio.gather(market.quote(sym), market.history(sym, "1Y"))
    fundamentals = statements = None
    if not excluded:
        fundamentals, statements = await asyncio.gather(market.fundamentals(sym), market.statements(sym))
    values = compute_snapshot(inst.kind, quote, history, fundamentals, statements)
    errors = {k: v.get("message") for k, v in values["_inputs"].items() if v.get("message")} or None
    for attempt in range(2):
        row = db.get(ScreenMetric, inst.id)
        now = datetime.now(UTC)
        if row is None:
            row = ScreenMetric(instrument_id=inst.id, provider=market.source, computed_at=now, values=values)
            db.add(row)
        else:
            row.provider, row.computed_at, row.values = market.source, now, values
        row.errors = errors
        try:
            db.commit()
            return row
        except IntegrityError:
            # Another request (e.g. a second panel of the same page) stored this snapshot first: update that row.
            db.rollback()
            if attempt:
                raise
    return row


def is_stale(row: ScreenMetric | None, hours: int) -> bool:
    if row is None:
        return True
    at = row.computed_at if row.computed_at.tzinfo else row.computed_at.replace(tzinfo=UTC)
    return at < datetime.now(UTC) - timedelta(hours=hours) or (row.values or {}).get("_version") != SNAPSHOT_VERSION


async def refresh_instruments(
    db: Session, market: MarketDataService, instruments: list[Instrument], *, hours: int, limit: int, progress=None
) -> dict:
    """Refresh missing or stale snapshots, oldest first, at most `limit`. Errors are recorded per instrument."""
    rows = {
        r.instrument_id: r
        for r in db.scalars(select(ScreenMetric).where(ScreenMetric.instrument_id.in_([i.id for i in instruments])))
    }
    due = [i for i in instruments if is_stale(rows.get(i.id), hours) or rows[i.id].provider != market.source]
    due.sort(key=lambda i: rows[i.id].computed_at if i.id in rows else datetime.min.replace(tzinfo=UTC))
    done, failed = 0, []
    for inst in due[:limit]:
        try:
            await build_snapshot(db, market, inst)
            done += 1
        except Exception as exc:  # one bad instrument must not stop the batch
            db.rollback()
            failed.append({"symbol": inst.symbol, "error": type(exc).__name__})
        if progress:
            progress(done + len(failed), min(len(due), limit))
    return {"due": len(due), "refreshed": done, "failed": failed, "remaining": max(0, len(due) - limit)}


# --------------------------------------------------------------------- universes
def _parse_spec(spec: dict | None) -> tuple[str, int | None]:
    spec = spec or {}
    kind = str(spec.get("kind") or "")
    if kind not in ("watchlists", "watchlist", "holdings", "list"):
        raise AppError(
            422, "bad_universe", "Choose a universe: all watchlists, one watchlist, holdings or a saved list."
        )
    uid = spec.get("id")
    if kind in ("watchlist", "list"):
        if not isinstance(uid, int):
            raise AppError(422, "bad_universe", "This universe needs the id of its watchlist or list.")
        return kind, uid
    return kind, None


def _holding_symbols(db: Session) -> list[str]:
    from marketdesk.services.portfolio import current_states

    states, _ = current_states(db)
    return [p.symbol for st in states.values() for p in st.open_positions]


def resolve_universe(db: Session, provider: str, spec: dict | None, max_size: int) -> dict:
    """{spec, label, instruments, excluded, truncated}: the members are explicit, bounded and in a stable order."""
    kind, uid = _parse_spec(spec)
    insts: list[Instrument] = []
    if kind == "watchlists":
        label = "All watchlists"
        items = db.scalars(
            select(WatchlistItem).join(Watchlist).order_by(Watchlist.position, Watchlist.id, WatchlistItem.position)
        )
        insts = [it.instrument for it in items]
    elif kind == "watchlist":
        wl = db.get(Watchlist, uid)
        if wl is None:
            raise AppError(404, "not_found", "That watchlist no longer exists.")
        label = f"Watchlist · {wl.name}"
        insts = [it.instrument for it in sorted(wl.items, key=lambda x: x.position)]
    elif kind == "holdings":
        label = "Current holdings"
        insts = [i for s in _holding_symbols(db) if (i := find_instrument(db, provider, s)) is not None]
    else:
        ul = db.get(ScreenUniverse, uid)
        if ul is None:
            raise AppError(404, "not_found", "That list no longer exists.")
        label = f"List · {ul.name}"
        insts = [i for s in ul.symbols if (i := find_instrument(db, provider, s)) is not None]
    seen: set[int] = set()
    members, excluded = [], []
    for inst in insts:
        if inst.id in seen or inst.provider != provider:
            continue
        seen.add(inst.id)
        if (inst.kind or "").upper() in EXCLUDED_KINDS:
            excluded.append(inst.symbol)
        else:
            members.append(inst)
    truncated = max(0, len(members) - max_size)
    return {
        "spec": {"kind": kind, "id": uid} if uid is not None else {"kind": kind},
        "label": label,
        "instruments": members[:max_size],
        "excluded": excluded,
        "truncated": truncated,
    }


def universe_options(db: Session, provider: str) -> list[dict]:
    wls = list(db.scalars(select(Watchlist).order_by(Watchlist.position, Watchlist.id)))
    out = [{"kind": "watchlists", "label": "All watchlists", "count": sum(len(w.items) for w in wls)}]
    out += [{"kind": "watchlist", "id": w.id, "label": f"Watchlist · {w.name}", "count": len(w.items)} for w in wls]
    out.append({"kind": "holdings", "label": "Current holdings", "count": len(set(_holding_symbols(db)))})
    for ul in db.scalars(select(ScreenUniverse).order_by(ScreenUniverse.name)):
        out.append(
            {
                "kind": "list",
                "id": ul.id,
                "label": f"List · {ul.name}",
                "count": len(ul.symbols),
                "name": ul.name,
                "symbols": list(ul.symbols),
            }
        )
    return out


def tracked_instruments(db: Session, provider: str, max_size: int) -> list[Instrument]:
    """Everything any universe can contain (for the worker's daily snapshot refresh)."""
    seen: dict[int, Instrument] = {}
    specs = [{"kind": "watchlists"}, {"kind": "holdings"}] + [
        {"kind": "list", "id": u} for u in db.scalars(select(ScreenUniverse.id))
    ]
    for spec in specs:
        for inst in resolve_universe(db, provider, spec, max_size)["instruments"]:
            seen.setdefault(inst.id, inst)
    for ps in db.scalars(select(PeerSet)):
        for s in ps.peers:
            inst = find_instrument(db, provider, s)
            if inst is not None:
                seen.setdefault(inst.id, inst)
    return list(seen.values())


# --------------------------------------------------------------------- screening
def _dec(v: Any, what: str) -> Decimal:
    try:
        d = Decimal(str(v).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as err:
        raise AppError(422, "bad_filter", f"{what} must be a plain number.") from err
    if not d.is_finite():
        raise AppError(422, "bad_filter", f"{what} must be a finite number.")
    return d


def validate_filters(filters: Any) -> list[dict]:
    if not isinstance(filters, list) or len(filters) > 12:
        raise AppError(422, "bad_filter", "A screen has at most 12 filters.")
    out = []
    for i, f in enumerate(filters, 1):
        if not isinstance(f, dict):
            raise AppError(422, "bad_filter", f"Filter {i} is not valid.")
        key, op = str(f.get("metric") or ""), str(f.get("op") or "")
        if key in TEXT_FIELDS:
            vals = f.get("values")
            if op != "in" or not isinstance(vals, list) or not vals or len(vals) > 30:
                raise AppError(422, "bad_filter", f"Filter {i}: choose one or more {TEXT_FIELDS[key].lower()} values.")
            out.append({"metric": key, "op": "in", "values": [str(v)[:80] for v in vals]})
            continue
        m = BY_KEY.get(key)
        if m is None:
            raise AppError(422, "bad_filter", f"Filter {i}: unknown metric {key!r}.")
        if op not in ("gte", "lte", "between"):
            raise AppError(422, "bad_filter", f"Filter {i}: the condition must be ≥, ≤ or between.")
        lo = _dec(f.get("value"), f"Filter {i} ({m.label})")
        clean: dict[str, Any] = {"metric": key, "op": op, "value": format(lo, "f")}
        if op == "between":
            hi = _dec(f.get("value2"), f"Filter {i} ({m.label}) upper bound")
            if hi < lo:
                raise AppError(422, "bad_filter", f"Filter {i} ({m.label}): the upper bound is below the lower bound.")
            clean["value2"] = format(hi, "f")
        if m.unit == "currency":
            ccy = str(f.get("currency") or "")
            if ccy not in ("INR", "USD"):
                raise AppError(
                    422, "bad_filter", f"Filter {i} ({m.label}): choose the currency of the amount (INR or USD)."
                )
            clean["currency"] = ccy
        out.append(clean)
    return out


def _convert(v: Decimal, from_ccy: str | None, to_ccy: str, rates: dict) -> Decimal | None:
    if from_ccy == to_ccy:
        return v
    r = rates.get(("USD", "INR"))
    if r is None or from_ccy not in ("USD", "INR"):
        return None
    return v * r if (from_ccy, to_ccy) == ("USD", "INR") else v / r


def _text(inst: Instrument, snap: dict | None, key: str) -> str | None:
    if key in ("sector", "industry"):
        return (snap or {}).get(key)
    return getattr(inst, key)


def evaluate(inst: Instrument, snap: dict | None, f: dict, rates: dict) -> tuple[str, str | None]:
    """('pass' | 'fail' | 'missing', reason)."""
    key = f["metric"]
    if key in TEXT_FIELDS:
        v = _text(inst, snap, key)
        if v is None:
            return "missing", f"{TEXT_FIELDS[key]} not reported."
        return ("pass" if v in f["values"] else "fail"), None
    if snap is None:
        return "missing", "Not loaded yet."
    cell = snap.get(key) or {}
    if cell.get("v") is None:
        return "missing", cell.get("why") or "No value."
    v = Decimal(cell["v"])
    if BY_KEY[key].unit == "currency":
        converted = _convert(v, inst.currency, f["currency"], rates)
        if converted is None:
            return "missing", f"In {inst.currency}; no usable USD/INR rate to compare with {f['currency']}."
        v = converted
    lo = Decimal(f["value"])
    ok = v >= lo if f["op"] == "gte" else v <= lo if f["op"] == "lte" else lo <= v <= Decimal(f["value2"])
    return ("pass" if ok else "fail"), None


def _instrument_row(inst: Instrument) -> dict:
    return {
        "symbol": inst.symbol,
        "name": inst.name,
        "exchange": inst.exchange,
        "currency": inst.currency,
        "country": inst.country,
        "kind": inst.kind,
    }


def _row(inst: Instrument, sm: ScreenMetric | None) -> dict:
    snap = sm.values if sm else None
    return {
        **_instrument_row(inst),
        "sector": (snap or {}).get("sector"),
        "industry": (snap or {}).get("industry"),
        "metrics": {m.key: (snap or {}).get(m.key) for m in METRICS} if snap else None,
        "computed_at": _iso(sm.computed_at) if sm else None,
        "inputs": (snap or {}).get("_inputs"),
    }


def _snapshots(db: Session, insts: list[Instrument]) -> dict[int, ScreenMetric]:
    if not insts:
        return {}
    return {
        r.instrument_id: r
        for r in db.scalars(select(ScreenMetric).where(ScreenMetric.instrument_id.in_([i.id for i in insts])))
    }


def dataset_status(insts: list[Instrument], snaps: dict[int, ScreenMetric], provider: str, hours: int) -> dict:
    loaded = [snaps[i.id] for i in insts if i.id in snaps and snaps[i.id].provider == provider]
    times = sorted(r.computed_at if r.computed_at.tzinfo else r.computed_at.replace(tzinfo=UTC) for r in loaded)
    return {
        "members": len(insts),
        "loaded": len(loaded),
        "stale": sum(1 for r in loaded if is_stale(r, hours)),
        "not_loaded": [i.symbol for i in insts if i.id not in snaps or snaps[i.id].provider != provider],
        "oldest": _iso(times[0]) if times else None,
        "newest": _iso(times[-1]) if times else None,
        "refresh_hours": hours,
    }


def _sort_rows(rows: list[dict], sort: dict | None) -> list[dict]:
    key = (sort or {}).get("key") or "symbol"
    desc = (sort or {}).get("dir") == "desc"
    if key in ("symbol", "name", "sector"):
        named = sorted((r for r in rows if r.get(key)), key=lambda r: str(r[key]).lower(), reverse=desc)
        return named + [r for r in rows if not r.get(key)]
    if key not in BY_KEY:
        return rows
    have = [r for r in rows if r["metrics"] and (r["metrics"].get(key) or {}).get("v") is not None]
    rest = [r for r in rows if r not in have]
    have.sort(key=lambda r: Decimal(r["metrics"][key]["v"]), reverse=desc)
    return have + rest  # missing values always last


def run_screen(
    db: Session, provider: str, spec: dict, filters: Any, sort: dict | None, rates: dict, *, max_size: int, hours: int
) -> dict:
    clean = validate_filters(filters)
    uni = resolve_universe(db, provider, spec, max_size)
    insts = uni["instruments"]
    snaps = _snapshots(db, insts)
    funnel = [{"filter": f, "passed": 0, "failed": 0, "missing": 0} for f in clean]
    matched = []
    for inst in insts:
        sm = snaps.get(inst.id) if (inst.id in snaps and snaps[inst.id].provider == provider) else None
        ok = True
        for i, f in enumerate(clean):
            res, _ = evaluate(inst, sm.values if sm else None, f, rates)
            funnel[i]["passed" if res == "pass" else "failed" if res == "fail" else "missing"] += 1
            ok = ok and res == "pass"
        if ok:
            matched.append(_row(inst, sm))
    used = [f["metric"] for f in clean if f["metric"] in BY_KEY]
    coverage = {}
    for key in dict.fromkeys([*used, *DEFAULT_COLUMNS]):
        vals = [snaps[i.id].values.get(key) or {} for i in insts if i.id in snaps]
        dates = sorted(c["as_of"][:10] for c in vals if c.get("v") is not None and c.get("as_of"))
        coverage[key] = {
            "with_value": sum(1 for c in vals if c.get("v") is not None),
            "members": len(insts),
            "as_of_min": dates[0] if dates else None,
            "as_of_max": dates[-1] if dates else None,
        }
    return {
        "universe": {k: v for k, v in uni.items() if k != "instruments"},
        "filters": clean,
        "funnel": funnel,
        "matched": len(matched),
        "rows": _sort_rows(matched, sort),
        "coverage": coverage,
        "dataset": dataset_status(insts, snaps, provider, hours),
        "fx": _fx_note(rates),
        "note": "Missing values never pass a filter. Screens read the stored snapshot; nothing is fetched to screen.",
    }


def _fx_note(rates: dict) -> dict | None:
    r = rates.get(("USD", "INR"))
    meta = rates.get("meta") or {}
    if r is None:
        return {
            "rate": None,
            "message": meta.get("message") or "No USD/INR rate: amounts in another currency are not compared.",
        }
    return {
        "pair": "USD/INR",
        "rate": format(r, "f"),
        "market_time": _iso(meta.get("market_time")),
        "status": meta.get("status"),
        "source": meta.get("source"),
    }


def export_csv(result: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    keys = [m.key for m in METRICS]
    w.writerow(
        [
            "symbol",
            "name",
            "exchange",
            "currency",
            "country",
            "sector",
            "industry",
            *[f"{k} ({BY_KEY[k].unit})" for k in keys],
            *[f"{k} as of" for k in keys],
            "snapshot_at",
        ]
    )
    for r in result["rows"]:
        ms = r["metrics"] or {}
        w.writerow(
            [
                safe_cell(x)
                for x in (
                    r["symbol"],
                    r["name"],
                    r["exchange"],
                    r["currency"],
                    r["country"],
                    r["sector"],
                    r["industry"],
                    *[(ms.get(k) or {}).get("v") or "" for k in keys],
                    *[((ms.get(k) or {}).get("as_of") or "")[:10] for k in keys],
                    r["computed_at"] or "",
                )
            ]
        )
    uni = result["universe"]
    w.writerow([])
    w.writerow(
        [
            safe_cell(
                f"Universe: {uni['label']}; {result['matched']} of {result['dataset']['members']} members matched. "
                "Blank cells are values the provider did not report."
            )
        ]
    )
    return buf.getvalue()


# --------------------------------------------------------------------- peers
def _mcap_inr(sm: ScreenMetric | None, inst: Instrument, rates: dict) -> Decimal | None:
    cell = (sm.values.get("market_cap") or {}) if sm else {}
    if cell.get("v") is None:
        return None
    return _convert(Decimal(cell["v"]), inst.currency, "INR", rates)


def suggest_peers(db: Session, inst: Instrument, provider: str, rates: dict, limit: int = 5) -> list[dict]:
    """Instruments with snapshots (watchlists, holdings, lists) sharing the industry, then the sector."""
    own = db.get(ScreenMetric, inst.id)
    sector, industry = (own.values.get("sector"), own.values.get("industry")) if own else (None, None)
    if not sector and not industry:
        return []
    my_cap = _mcap_inr(own, inst, rates)
    cands = []
    for sm in db.scalars(
        select(ScreenMetric).where(ScreenMetric.instrument_id != inst.id, ScreenMetric.provider == provider)
    ):
        other = db.get(Instrument, sm.instrument_id)
        if other is None or (other.kind or "").upper() in EXCLUDED_KINDS:
            continue
        same_ind = industry and sm.values.get("industry") == industry
        same_sec = sector and sm.values.get("sector") == sector
        if not (same_ind or same_sec):
            continue
        cap = _mcap_inr(sm, other, rates)
        dist = abs(math.log(float(cap) / float(my_cap))) if cap and my_cap and cap > 0 and my_cap > 0 else 99.0
        reason = f"Same industry ({industry})" if same_ind else f"Same sector ({sector})"
        cands.append(
            (0 if same_ind else 1, 0 if other.country == inst.country else 1, dist, other.symbol, other, reason)
        )
    cands.sort(key=lambda c: c[:4])
    return [{"symbol": c[4].symbol, "reason": c[5]} for c in cands[:limit]]


def set_peers(db: Session, inst: Instrument, symbols: list[str]) -> PeerSet:
    ps = db.scalar(select(PeerSet).where(PeerSet.instrument_id == inst.id))
    if ps is None:
        ps = PeerSet(instrument_id=inst.id, peers=list(symbols))
        db.add(ps)
    else:
        ps.peers = list(symbols)
    db.commit()
    return ps


def peer_table(db: Session, inst: Instrument, peers: list[Instrument], provider: str) -> list[dict]:
    snaps = _snapshots(db, [inst, *peers])
    return [
        _row(i, snaps.get(i.id) if (i.id in snaps and snaps[i.id].provider == provider) else None)
        for i in [inst, *peers]
    ]


# --------------------------------------------------------------------- heatmap
def heatmap(
    db: Session, provider: str, spec: dict, metric: str, weighting: str, rates: dict, *, max_size: int, hours: int
) -> dict:
    if metric not in HEATMAP_METRICS:
        raise AppError(422, "bad_metric", "Choose 1-day, 1-month, 3-month or 1-year change.")
    if weighting not in ("equal", "market_cap"):
        raise AppError(422, "bad_weighting", "Weighting is equal or market cap.")
    uni = resolve_universe(db, provider, spec, max_size)
    insts = uni["instruments"]
    snaps = _snapshots(db, insts)
    notes = []
    currencies = {i.currency for i in insts}
    effective = weighting
    if weighting == "market_cap" and len(currencies) > 1 and rates.get(("USD", "INR")) is None:
        effective = "equal"
        notes.append(
            "Market-cap weights need a USD/INR rate to combine INR and USD listings; none is available, so "
            "sectors are equal-weighted."
        )
    groups: dict[str, list[dict]] = {}
    for inst in insts:
        sm = snaps.get(inst.id) if (inst.id in snaps and snaps[inst.id].provider == provider) else None
        snap = sm.values if sm else {}
        sector = snap.get("sector") or "Sector not reported"
        cell = snap.get(metric) or {}
        cap = _mcap_inr(sm, inst, rates) if effective == "market_cap" else None
        groups.setdefault(sector, []).append(
            {
                "symbol": inst.symbol,
                "name": inst.name,
                "value": cell.get("v"),
                "why": cell.get("why") if sm else "Not loaded yet.",
                "as_of": cell.get("as_of"),
                "market_cap_inr": _s(cap, 0) if cap is not None else None,
            }
        )
    sectors = []
    for name, members in groups.items():
        with_value = [m for m in members if m["value"] is not None]
        if effective == "market_cap":
            weighted = [m for m in with_value if m["market_cap_inr"] is not None and Decimal(m["market_cap_inr"]) > 0]
            total = sum((Decimal(m["market_cap_inr"]) for m in weighted), Decimal(0))
            value = sum(Decimal(m["value"]) * Decimal(m["market_cap_inr"]) for m in weighted) / total if total else None
            used = len(weighted)
        else:
            total = Decimal(0)
            value = sum(Decimal(m["value"]) for m in with_value) / len(with_value) if with_value else None
            used = len(with_value)
        sectors.append(
            {
                "sector": name,
                "members": len(members),
                "used": used,
                "value": _s(value, 2),
                "weight_total_inr": _s(total, 0) if effective == "market_cap" else None,
                "items": sorted(members, key=lambda m: m["symbol"]),
            }
        )
    sectors.sort(key=lambda s: (s["value"] is None, -Decimal(s["value"]) if s["value"] is not None else 0, s["sector"]))
    return {
        "universe": {k: v for k, v in uni.items() if k != "instruments"},
        "metric": metric,
        "weighting": effective,
        "requested_weighting": weighting,
        "sectors": sectors,
        "dataset": dataset_status(insts, snaps, provider, hours),
        "fx": _fx_note(rates) if effective == "market_cap" and len(currencies) > 1 else None,
        "notes": notes,
        "method": (
            "Each tile is the sector's average of the chosen change across members with a value, "
            + (
                "weighted by market cap (in INR at the stated USD/INR rate where needed)."
                if effective == "market_cap"
                else "equally weighted."
            )
        ),
    }


# --------------------------------------------------------------------- saved screens/lists
def screen_dict(s: SavedScreen) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "universe": s.universe,
        "filters": s.filters,
        "sort": s.sort,
        "created_at": _iso(s.created_at),
        "updated_at": _iso(s.updated_at),
    }


# --------------------------------------------------------------------- background refresh
class RefreshJob:
    """At most one on-demand snapshot refresh at a time (the worker refreshes a few per cycle on its own)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {"running": False}

    def start(self, label: str, run) -> bool:
        with self._lock:
            if self.state.get("running"):
                return False
            self.state = {
                "running": True,
                "label": label,
                "done": 0,
                "total": None,
                "started_at": datetime.now(UTC).isoformat(),
            }

        def progress(done: int, total: int) -> None:
            self.state.update(done=done, total=total)

        def target() -> None:
            try:
                result = asyncio.run(run(progress))
                self.state.update(running=False, finished_at=datetime.now(UTC).isoformat(), result=result)
            except Exception as exc:  # pragma: no cover - surfaced in the job state
                self.state.update(running=False, finished_at=datetime.now(UTC).isoformat(), error=type(exc).__name__)

        threading.Thread(target=target, name="screener-refresh", daemon=True).start()
        return True


REFRESH_JOB = RefreshJob()

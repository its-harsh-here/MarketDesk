"""Terminal T2: assemble the financial-analysis view from SEC company facts (US registrants) or the provider's
annual statements (other listings, labelled unofficial). The arithmetic is in ``fin_analysis``."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from marketdesk.models import Instrument
from marketdesk.services import fin_analysis as fa
from marketdesk.services.market import MarketDataService

ANNUAL_PERIODS, QUARTERLY_PERIODS = 10, 12


def _out(x):
    if isinstance(x, Decimal):
        return format(x.quantize(Decimal("0.0001")), "f")
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, dict):
        return {k: _out(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_out(v) for v in x]
    return x


async def _bands(market: MarketDataService, inst: Instrument, annual: dict) -> dict:
    hist, acts = await asyncio.gather(market.history(inst.symbol, "5Y"), market.actions(inst.symbol))
    if hist.value is None or not hist.value.bars:
        return {"pe": None, "ev_ebitda": None, "reason": hist.meta.message or "No daily price history."}
    bars = [(b.session_date, b.close) for b in hist.value.bars if b.close is not None]
    splits = [(a.action_date, a.value) for a in (acts.value or []) if a.kind == "SPLIT"]
    out = fa.valuation_bands(annual, bars, splits, inst.currency)
    out["price_source"] = f"{market.label} daily closes ({hist.value.adjustment})"
    out["splits_source"] = f"{market.label} corporate actions" if acts.value is not None else None
    return out


def _month_end(y: int, m: int) -> date:
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)


def _quarter_gaps(st: dict) -> list[date]:
    """Quarter ends missing between reported quarters (the provider sometimes skips one; it is never derived)."""
    ends = sorted({v["end"] for line in st["lines"] if line["kind"] == "duration" for v in line["values"]})
    gaps = []
    for a, b in zip(ends, ends[1:], strict=False):
        missing = round((b - a).days / 91.3) - 1
        gaps += [_month_end(a.year, a.month + 3 * (k + 1)) for k in range(max(0, missing))]
    return gaps


async def provider_statements(market: MarketDataService, inst: Instrument, period: str, max_periods: int | None,
                              price=None, price_date=None, price_ccy=None) -> dict:  # fmt: skip
    """Research envelope (same shape as the SEC statements) from the provider's full statement tables."""
    from marketdesk.services.financials import compute_ratios

    r = await market.reported(inst.symbol, period)
    base = {"symbol": inst.symbol, "source": market.label, "fetched_at": r.meta.fetched_at}
    if r.value is None:
        return {**base, "status": r.meta.status if r.meta.status != "available" else "missing",
                "reason": r.meta.message or f"The provider has no {period} statements for this listing."}  # fmt: skip
    st = dict(r.value)
    n = max_periods or (5 if period == "annual" else 8)
    st["period_ends"] = st["period_ends"][:n]
    keep = set(st["period_ends"])
    st["lines"] = [{**line, "values": [v for v in line["values"] if v["end"] in keep]} for line in st["lines"]]
    st["ratios"] = compute_ratios(st, price, price_date, price_ccy)
    notes = []
    if period == "quarterly":
        gaps = [g for g in _quarter_gaps(st) if g > min(keep)] if keep else []
        if gaps:
            when = ", ".join(g.strftime("%b %Y") for g in gaps)
            notes.append(f"The source skips the quarter ending {when}; missing quarters are not derived.")
        notes.append("Indian companies publish a balance sheet and cash flow half-yearly, so those tables have "
                     "fewer quarters." if inst.country == "IN" else "Balance-sheet and cash-flow quarters are "
                     "shown where the source reports them.")  # fmt: skip
    st["coverage_note"] = " ".join(notes) or None
    st["entity"] = inst.name
    st["facts_url"] = None
    return _out({**base, "status": r.meta.status, "reason": None, "data": st})


async def build(db: Session, market: MarketDataService, research, inst: Instrument, period: str) -> dict:
    base = {"symbol": inst.symbol, "period": period}
    if inst.country == "US" and research is not None and research.client.enabled:
        n = ANNUAL_PERIODS if period == "annual" else QUARTERLY_PERIODS
        env = await asyncio.to_thread(research.financials, db, inst, period, None, None, None, n)
        st = env.get("data")
        if st and st.get("period_ends"):
            annual = st
            if period != "annual":
                aenv = await asyncio.to_thread(
                    research.financials, db, inst, "annual", None, None, None, ANNUAL_PERIODS
                )
                annual = aenv.get("data") or {}
            bands = await _bands(market, inst, annual) if annual.get("period_ends") else {"reason": "No annual data."}
            return _out(
                {
                    **base,
                    "status": env["status"],
                    "source": "SEC EDGAR company facts (as filed; latest filing wins, earlier values kept as "
                    "restatements)",
                    "official": True,
                    "currency": st.get("currency"),
                    "template": st.get("template"),
                    "fetched_at": env.get("fetched_at"),
                    "facts_url": st.get("facts_url"),
                    **fa.analysis(st),
                    "bands": bands,
                }
            )
        if env.get("status") not in ("not_applicable",):
            return {**base, "status": env.get("status"), "reason": env.get("reason") or "No SEC statements."}
    full = await market.reported(inst.symbol, period)
    if full.value is not None and full.value.get("period_ends"):
        st = full.value
        annual = st
        if period != "annual":
            a = await market.reported(inst.symbol, "annual")
            annual = a.value or {}
        bands = await _bands(market, inst, annual) if annual.get("period_ends") else {"reason": "No annual data."}
        lag = annual.get("lines") and next((v["filed"] for ln in annual["lines"] for v in ln["values"]), None)
        if lag and isinstance(bands, dict):
            bands["note"] = (
                (bands.get("note") or "")
                + " Each fiscal year is used from "
                + (
                    "60 days after its end (the SEBI deadline for annual audited results)"
                    if inst.country == "IN"
                    else "90 days after its end"
                )  # fmt: skip
                + ", since the source gives no publication dates."
            ).strip()
        return _out(
            {
                **base,
                "status": full.meta.status,
                "source": "Reported statements (unofficial provider data)",
                "official": False,
                "currency": st.get("currency"),
                "fetched_at": full.meta.fetched_at,
                "notes": [],
                **fa.analysis(st),
                "bands": bands,
            }
        )
    r = await market.statements(inst.symbol)
    if r.value is None or not r.value.periods:
        return {
            **base,
            "status": "missing",
            "reason": r.meta.message or "The provider has no annual statements for this listing.",
        }
    st = fa.from_provider(r.value.periods, r.value.source)
    an = fa.analysis(st)
    note = (
        "Quarterly statements come from SEC filings (US registrants); this listing has annual provider statements only."
        if period != "annual"
        else None
    )
    return _out(
        {
            **base,
            "period": "annual",
            "status": r.meta.status,
            "source": f"{r.value.source} (unofficial provider data; up to {len(r.value.periods)} fiscal years)",
            "official": False,
            "currency": None,
            "fetched_at": r.meta.fetched_at,
            "notes": [*r.value.notes, st["provider_note"], *([note] if note else [])],
            **an,
            "bands": {
                "pe": None,
                "ev_ebitda": None,
                "reason": "Valuation bands need reported EPS, share counts and EBITDA with filing dates; "
                "the provider's statements do not include them.",
            },
        }
    )

"""Terminal T2: assemble the financial-analysis view from SEC company facts (US registrants) or the provider's
annual statements (other listings, labelled unofficial). The arithmetic is in ``fin_analysis``."""

from __future__ import annotations

import asyncio
from datetime import date
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
    out["price_source"] = f"{market.source} daily closes ({hist.value.adjustment})"
    out["splits_source"] = f"{market.source} corporate actions" if acts.value is not None else None
    return out


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

"""Security description (terminal roadmap T1): one view of identity, business, key statistics and data coverage.

Every block carries its source and date. Nothing is filled in from elsewhere: a missing block says why. The business
summary for US registrants is quoted from the latest 10-K (Item 1); other listings show the market-data provider's
profile, marked as such, when the provider supplies one."""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.models import Instrument, InstrumentIdentifier, ScreenMetric
from marketdesk.providers.base import ProviderError
from marketdesk.services import screener
from marketdesk.services.market import MarketDataService
from marketdesk.services.market_views import fundamentals_payload

SUMMARY_CHARS = 1400
_BUSINESS_HEAD = re.compile(r"item\s*1\.?\s*[\-–—:]?\s*business\b", re.IGNORECASE)
_NEXT_ITEM = re.compile(r"item\s*1a\.?\s*[\-–—:]?\s*risk\s+factors", re.IGNORECASE)
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)


def business_section(text: str) -> str | None:
    """The longest 'Item 1. Business' section, up to 'Item 1A. Risk Factors' (the table of contents entry is
    short). Returns None when no section of reasonable length is found."""
    text = text.translate(_ZERO_WIDTH)
    best = None
    for m in _BUSINESS_HEAD.finditer(text):
        tail = text[m.end() : m.end() + 400_000]
        stop = _NEXT_ITEM.search(tail)
        body = tail[: stop.start()] if stop else tail[:60_000]
        if best is None or len(body) > len(best):
            best = body
    return best if best and len(best) > 400 else None


def summary_excerpt(section: str, limit: int = SUMMARY_CHARS) -> str:
    """The opening paragraphs (80+ characters, i.e. not headings) of a section, whole, up to `limit` characters."""
    out: list[str] = []
    size = 0
    for line in section.split("\n"):
        p = re.sub(r"\s+", " ", line).strip()
        if len(p) < 80:
            continue
        if out and size + len(p) > limit:
            break
        out.append(p if len(p) <= limit else p[: limit - 1].rstrip() + "…")
        size += len(p)
    return "\n\n".join(out)


async def _sec_summary(db: Session, research, inst: Instrument) -> dict:
    from marketdesk.services.earnings import _filing_text

    env = await asyncio.to_thread(research.filings, db, inst, 80)
    tenk = next((r for r in env.get("data") or [] if r["form"] in ("10-K", "20-F", "40-F")), None)
    if tenk is None:
        return {"status": "missing", "reason": "No annual report (10-K/20-F) is listed for this company."}
    key = f"sec:business:{tenk['accession']}"
    payload, fetched = await asyncio.to_thread(research._cache_get, db, key)
    if payload is None:
        try:
            text, url = await _filing_text(research, env.get("cik"), tenk)
        except ProviderError as err:
            return {"status": "unavailable", "reason": f"Could not read the annual report: {err.message}"}
        section = await asyncio.to_thread(business_section, text)
        payload = {
            "text": summary_excerpt(section) if section else None,
            "url": url,
            "form": tenk["form"],
            "filing_date": tenk["filing_date"],
            "report_date": tenk.get("report_date"),
        }
        await asyncio.to_thread(research._cache_put, db, key, "sec_business", payload)
        fetched = datetime.now(UTC)
    if not payload.get("text"):
        return {
            "status": "missing",
            "reason": f"No 'Item 1. Business' section was found in the {payload['form']} filed "
            f"{payload['filing_date']}.",
            "url": payload.get("url"),
        }
    return {
        "status": "available",
        "kind": "filing",
        "text": payload["text"],
        "source": f"SEC EDGAR · {payload['form']} Item 1 (Business), quoted",
        "url": payload["url"],
        "as_of": payload["filing_date"],
        "period": payload.get("report_date"),
        "fetched_at": fetched.isoformat() if fetched else None,
    }


async def _summary(db: Session, market: MarketDataService, research, inst: Instrument, fund: dict) -> dict:
    if inst.country == "US" and research is not None and research.client.enabled:
        sec = await _sec_summary(db, research, inst)
        if sec["status"] == "available":
            return sec
    else:
        sec = None
    text = (fund.get("values") or {}).get("summary")
    if text:
        return {
            "status": "available",
            "kind": "provider",
            "text": text if len(text) <= SUMMARY_CHARS * 2 else text[: SUMMARY_CHARS * 2 - 1].rstrip() + "…",
            "source": f"{market.source} company profile, as supplied by the provider (not verified)",
            "url": None,
            "as_of": None,
            "fetched_at": fund["meta"].get("fetched_at"),
        }
    reason = (
        sec["reason"]
        if sec
        else (
            "The provider did not supply a company profile for this listing."
            + (
                " Yahoo refuses its company-summary endpoint from some cloud servers."
                if market.source == "yahoo"
                else ""
            )
        )
    )
    if inst.country == "US" and (research is None or not research.client.enabled):
        reason = "SEC data is not configured on this server (SEC_USER_AGENT), and " + reason[0].lower() + reason[1:]
    return {"status": "missing", "reason": reason}


def _identity(db: Session, inst: Instrument, fund: dict, profile: dict | None) -> dict:
    ids = list(db.scalars(select(InstrumentIdentifier).where(InstrumentIdentifier.instrument_id == inst.id)))
    related = []
    for i in ids:
        if i.scheme.upper() in ("CIK", "ISIN"):
            for other in db.scalars(
                select(Instrument)
                .join(InstrumentIdentifier, InstrumentIdentifier.instrument_id == Instrument.id)
                .where(
                    InstrumentIdentifier.scheme == i.scheme,
                    InstrumentIdentifier.value == i.value,
                    Instrument.id != inst.id,
                )
            ):
                related.append({"symbol": other.symbol, "exchange": other.exchange, "via": i.scheme.upper()})
    fv = fund.get("values") or {}
    sec = (profile or {}).get("data") or {}
    fye = sec.get("fiscal_year_end")  # SEC gives MMDD
    return {
        "symbol": inst.symbol,
        "name": inst.name,
        "exchange": inst.exchange,
        "mic": inst.mic,
        "country": inst.country,
        "currency": inst.currency,
        "kind": inst.kind,
        "timezone": inst.timezone,
        "identity_source": inst.identity_source,
        "identity_verified_at": inst.identity_verified_at.isoformat() if inst.identity_verified_at else None,
        "identifiers": [
            {
                "scheme": i.scheme,
                "value": i.value,
                "source": i.source,
                "verified_at": i.verified_at.isoformat() if i.verified_at else None,
            }
            for i in ids
        ],
        "cik": (profile or {}).get("cik"),
        "sec": (
            {
                "name": sec.get("name"),
                "sic": sec.get("sic"),
                "industry": sec.get("industry"),
                "tickers": sec.get("tickers") or [],
                "exchanges": sec.get("exchanges") or [],
                "state_of_incorporation": sec.get("state_of_incorporation"),
                "fiscal_year_end": f"{fye[:2]}-{fye[2:]}" if isinstance(fye, str) and len(fye) == 4 else None,
                "fetched_at": (profile or {}).get("fetched_at"),
            }
            if sec
            else None
        ),
        "related_listings": related,
        "sector": fv.get("sector"),
        "industry": fv.get("industry"),
        "last_fiscal_year_end": fv.get("last_fiscal_year_end"),
        "most_recent_quarter": fv.get("most_recent_quarter"),
        "classification_source": f"{fund['meta'].get('source')} fundamentals" if fv else None,
        "fetched_at": fund["meta"].get("fetched_at"),
    }


async def _key_stats(db: Session, market: MarketDataService, inst: Instrument, hours: int) -> dict:
    row = db.get(ScreenMetric, inst.id)
    if row is None or row.provider != market.source or screener.is_stale(row, hours):
        row = await screener.build_snapshot(db, market, inst)
    vals = row.values or {}
    stats = []
    for m in screener.METRICS:
        v = vals.get(m.key) or {}
        stats.append(
            {
                **{k: getattr(m, k) for k in ("key", "label", "group", "unit", "source", "formula")},
                "value": v.get("v"),
                "as_of": v.get("as_of"),
                "why": v.get("why"),
            }
        )
    return {
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        "provider": row.provider,
        "inputs": vals.get("_inputs"),
        "stats": stats,
    }


def _coverage(inst: Instrument, market: MarketDataService, research, ai_enabled: bool, stats: dict) -> list[dict]:
    us = inst.country == "US"
    india = inst.country == "IN"
    sec_on = research is not None and research.client.enabled
    sample = market.source == "fixture"
    src = "Sample dataset" if sample else f"{market.source} (delayed, unofficial)"
    inputs = stats.get("inputs") or {}

    def ok(name: str) -> bool:
        return (inputs.get(name) or {}).get("status") in ("available", "cached", "stale", "sample")

    def row(domain, code, status, source, note=None, tab=None):
        if status == "missing" and not note:
            note = "The data provider returned nothing for this listing."
        return {"domain": domain, "code": code, "status": status, "source": source, "note": note, "tab": tab}

    out = [
        row("Daily prices and chart", "GP", "available" if ok("history") else "missing", src, None, "chart"),
        row(
            "Intraday and streaming quotes",
            None,
            "not_configured",
            None,
            "Needs a streaming feed (Alpaca for US, roadmap M04). Indian prices are polled and delayed.",
        ),
        row("Key statistics", "DES", "available" if ok("quote") else "missing", src, None, "description"),
        row(
            "Financial statements",
            "FA",
            "available" if (us and sec_on) or ok("statements") else "missing",
            "SEC EDGAR company facts" if us and sec_on else f"{src} annual statements",
            None if us and sec_on else ("Unofficial provider data; up to four fiscal years." if not sample else None),
            "financials",
        ),
        row(
            "Filings",
            "CN",
            "available" if us and sec_on else ("not_configured" if us else "not_available"),
            "SEC EDGAR" if us else None,
            None
            if us and sec_on
            else (
                "SEC data needs SEC_USER_AGENT on the server."
                if us
                else (
                    "Exchange announcements need a permitted source (BSE licence or verified NSE terms)."
                    if india
                    else "No filing source applies to this listing (no recorded country)."
                )
            ),
            "filings",
        ),
        row(
            "Results dates",
            "ERN",
            "available" if us and sec_on else ("estimated" if india else "not_available"),
            "SEC 8-K Item 2.02 history" if us else ("SEBI LODR 33(3) deadline" if india else None),
            "Next date is an estimate from past filings, never an announced date."
            if us
            else (
                "A regulatory deadline, not an announced date."
                if india
                else "Results dates come from SEC filings (US) or the SEBI deadline (India); neither applies."
            ),
            "earnings",
        ),
        row("Dividends and splits", "DVD", "available" if ok("history") else "missing", src, None, "events"),
        row("Peers and relative value", "RV", "available", "Your declared universes (M06 snapshots)", None, "peers"),
        row("Valuation scenarios", "DCF", "available", "Your assumptions on reported cash flows", None, "valuation"),
        row(
            "Consensus estimates and analyst ratings",
            "ANR",
            "licensed",
            None,
            "Licensed data; shown only if you subscribe to a provider that permits personal use.",
        ),
        row(
            "Insider transactions",
            "HDS",
            "planned" if us else "not_available",
            "SEC Form 4" if us else None,
            "Planned (terminal roadmap T3)."
            if us
            else (
                "Indian insider disclosures need a permitted exchange source."
                if india
                else "No insider-transaction source applies to this listing."
            ),
        ),
        row(
            "Institutional holders / shareholding pattern",
            "HDS",
            "planned" if us else "not_available",
            "SEC Form 13F data sets" if us else None,
            "Planned (terminal roadmap T3)."
            if us
            else (
                "Quarterly shareholding patterns need a permitted source (BSE licence or verified NSE terms)."
                if india
                else "No holdings source applies to this listing."
            ),
        ),
        row(
            "Short interest",
            None,
            "planned" if us else "not_available",
            "FINRA" if us else None,
            "Planned (terminal roadmap T6)."
            if us
            else ("Not published comparably for Indian listings." if india else "No short-interest source applies."),
        ),
        row(
            "Options",
            None,
            "licensed",
            None,
            "Needs an options data entitlement (terminal roadmap T7).",
        ),
        row(
            "AI research summaries",
            "ASK",
            "available" if ai_enabled else "not_configured",
            "Cited answers from retrieved evidence" if ai_enabled else None,
            None if ai_enabled else "AI research is off on this server.",
        ),
    ]
    return out


async def describe(
    db: Session, market: MarketDataService, research, settings, inst: Instrument, ai_enabled: bool
) -> dict:
    fund = await fundamentals_payload(market, inst.symbol)
    profile = None
    if inst.country == "US" and research is not None and research.client.enabled:
        profile = await asyncio.to_thread(research.profile, db, inst)
    # One database session: these run one after the other, never concurrently.
    summary = await _summary(db, market, research, inst, fund)
    stats = await _key_stats(db, market, inst, settings.screener_snapshot_hours)
    return {
        "symbol": inst.symbol,
        "identity": _identity(db, inst, fund, profile),
        "summary": summary,
        "key_stats": stats,
        "coverage": _coverage(inst, market, research, ai_enabled, stats),
        "metric_groups": list(dict.fromkeys(m.group for m in screener.METRICS)),
        "catalog": [asdict(m) for m in screener.METRICS],
    }

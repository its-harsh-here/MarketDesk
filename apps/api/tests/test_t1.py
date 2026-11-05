"""Terminal T1: description view — business summary from 10-K Item 1 (quoted), provider profile marked as such,
key statistics with as-of dates, coverage with reasons; cached fundamentals without a summary still load."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from marketdesk.services import description as ds

PARA = "We design, license and support small modular reactors for utilities and industrial customers worldwide. "


def tenk(body_paras: int = 4) -> str:
    toc = "Table of Contents\nItem 1. Business 4\nItem 1A. Risk Factors 12\n"
    body = "\n".join(f"{PARA}Paragraph {i} adds detail about operations and markets." for i in range(body_paras))
    return f"{toc}PART I\nItem 1. Business\nOverview\n{body}\nItem 1A. Risk Factors\nRisks follow here and there."


def test_business_section_skips_the_table_of_contents_and_quotes_whole_paragraphs():
    sec = ds.business_section(tenk())
    assert sec is not None and "Risks follow" not in sec and "Paragraph 3" in sec
    ex = ds.summary_excerpt(sec, limit=400)
    assert ex.startswith("We design") and "Overview" not in ex  # headings (short lines) are skipped
    assert "Paragraph 0" in ex and "Paragraph 3" not in ex  # whole paragraphs only, within the limit
    assert ds.business_section("Item 1. Business 4\nItem 1A. Risk Factors") is None


class _Client:
    enabled = True


class _Research:
    client = _Client()

    def __init__(self):
        self.cache = {}

    def filings(self, db, inst, limit):
        return {
            "cik": 1234,
            "data": [
                {"form": "8-K", "accession": "0001-26-1", "filing_date": "2026-10-01"},
                {"form": "10-K", "accession": "0001-26-2", "filing_date": "2026-03-01", "report_date": "2025-12-31"},
            ],
        }

    def _cache_get(self, db, key):
        return self.cache.get(key, (None, None))

    def _cache_put(self, db, key, kind, payload):
        self.cache[key] = (payload, datetime.now(UTC))


def test_sec_summary_is_quoted_with_form_date_and_link_and_cached(monkeypatch):
    calls = []

    async def fake_text(research, cik, filing):
        calls.append(filing["accession"])
        return tenk(), "https://www.sec.gov/Archives/edgar/data/1234/x/doc.htm"

    import marketdesk.services.earnings as er

    monkeypatch.setattr(er, "_filing_text", fake_text)

    class Inst:
        country = "US"

    r = _Research()
    out = asyncio.run(ds._sec_summary(None, r, Inst()))
    assert out["status"] == "available" and out["kind"] == "filing" and out["text"].startswith("We design")
    assert out["as_of"] == "2026-03-01" and out["period"] == "2025-12-31" and "10-K Item 1" in out["source"]
    assert out["url"].startswith("https://www.sec.gov/")
    asyncio.run(ds._sec_summary(None, r, Inst()))
    assert calls == ["0001-26-2"]  # the second call is served from the cache


def test_description_api_on_sample_data(api):
    d = api.get("/api/terminal/description", params={"symbol": "SX:AURORA"}).json()
    assert d["identity"]["symbol"] == "SX:AURORA" and d["identity"]["currency"] == "INR"
    assert d["identity"]["sector"] and d["identity"]["classification_source"].startswith("fixture")
    s = d["summary"]
    assert s["status"] == "available" and s["kind"] == "provider" and "fictitious" in s["text"]
    assert "not verified" in s["source"]
    stats = {x["key"]: x for x in d["key_stats"]["stats"]}
    assert stats["last_price"]["value"] and stats["last_price"]["as_of"]
    assert all(x["value"] is not None or x["why"] for x in stats.values())  # every gap is explained
    assert d["key_stats"]["computed_at"] and d["key_stats"]["provider"] == "fixture"
    cov = {(c["domain"]): c for c in d["coverage"]}
    assert cov["Filings"]["status"] == "not_available" and cov["Filings"]["note"]
    assert cov["Consensus estimates and analyst ratings"]["status"] == "licensed"
    assert all(c["status"] == "available" or c["note"] for c in d["coverage"])  # anything missing says why
    assert api.get("/api/terminal/description", params={"symbol": "SX:NOPE"}).status_code in (404, 422)


def test_fundamentals_cached_before_t1_still_decode():
    from marketdesk.providers.base import Fundamentals, InstrumentRef
    from marketdesk.providers.serialize import fundamentals_from, fundamentals_to

    f = Fundamentals(InstrumentRef("X", "X", None, "INR", None, None), None, None, None, None, None, None, None, None,
                     None, None, [], summary="Profile.")  # fmt: skip
    d = fundamentals_to(f)
    assert fundamentals_from(d).summary == "Profile."
    d.pop("summary")
    assert fundamentals_from(d).summary is None


def test_coverage_notes_follow_the_listing_country():
    from types import SimpleNamespace

    class _R:
        client = SimpleNamespace(enabled=True)

    mk = SimpleNamespace(source="yahoo")
    stats = {"inputs": {k: {"status": "available"} for k in ("quote", "history", "statements")}}
    us = {c["domain"]: c for c in ds._coverage(SimpleNamespace(country="US"), mk, _R(), True, stats)}
    india = {c["domain"]: c for c in ds._coverage(SimpleNamespace(country="IN"), mk, _R(), True, stats)}
    assert us["Filings"]["status"] == "available" and us["Insider transactions"]["status"] == "planned"
    assert us["Results dates"]["source"] == "SEC 8-K Item 2.02 history"
    assert india["Filings"]["status"] == "not_available" and "BSE licence" in india["Filings"]["note"]
    assert india["Results dates"]["status"] == "estimated" and "deadline" in india["Results dates"]["note"]
    assert "unofficial" in india["Daily prices and chart"]["source"]

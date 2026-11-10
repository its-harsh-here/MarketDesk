"""Terminal T5: news and filings stream — yfinance news normalisation (both shapes, unsafe links dropped), plain
8-K item labels, de-duplication and ordering, cache round trip, fake-SEC stream, API on sample data."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from marketdesk.api.app import create_app
from marketdesk.db import db_session
from marketdesk.models import Instrument
from marketdesk.providers.base import NewsItem
from marketdesk.providers.serialize import CODECS
from marketdesk.providers.yahoo import normalize_news
from marketdesk.services import news_stream as ns
from marketdesk.services.research import ResearchService

from .conftest import make_settings, migrated
from .test_m02_research import FakeSec


def test_normalize_news_handles_both_yfinance_shapes():
    content = {"title": " Apple unveils thing ", "pubDate": "2026-11-09T14:30:00Z", "contentType": "STORY",
               "provider": {"displayName": "Reuters"}, "canonicalUrl": {"url": "https://example.com/a?x=1"},
               "summary": "body text"}  # fmt: skip
    new = [{"id": "x", "content": content}]
    old = [
        {"title": "Old shape", "publisher": "AP", "link": "https://example.org/b", "providerPublishTime": 1762700000}
    ]
    bad = [
        {"content": {"title": "No link"}},
        {"title": "JS link", "link": "javascript:alert(1)"},
        "junk",
        {"title": ""},
    ]
    a = normalize_news(new)[0]
    assert a.title == "Apple unveils thing" and a.publisher == "Reuters" and a.kind == "news"
    assert a.url == "https://example.com/a?x=1" and a.published_at == datetime(2026, 11, 9, 14, 30, tzinfo=UTC)
    assert not hasattr(a, "summary")  # no body text is kept
    b = normalize_news(old)[0]
    assert b.publisher == "AP" and b.published_at.tzinfo is UTC
    assert normalize_news(bad) == [] and normalize_news(None) == []
    assert len(normalize_news(old * 50, limit=5)) == 5


def test_news_cache_round_trip():
    items = [NewsItem("T", "P", "https://x.test/1", datetime(2026, 1, 2, 3, 4, tzinfo=UTC), "news"),
             NewsItem("U", None, None, None, "press_release")]  # fmt: skip
    enc, dec = CODECS["news"]
    assert dec(enc(items)) == items


def test_filing_items_use_plain_8k_labels():
    r = {"form": "8-K", "filing_date": "2026-11-02", "items": ["2.02", "9.01"], "document_url": "https://sec/doc",
         "index_url": "https://sec/idx"}  # fmt: skip
    it = ns.filing_item(r)
    assert it["headline"] == "Results of operations (earnings release)" and it["category"] == "release"
    assert it["important"] and [i["code"] for i in it["items"]] == ["2.02", "9.01"] and it["url"] == "https://sec/doc"
    multi = ns.filing_item({**r, "form": "8-K/A", "items": ["5.02", "1.01"]})
    assert multi["headline"] == "Director or officer change, or executive pay; Entered a material agreement (amended)"
    q = ns.filing_item({"form": "10-Q", "filing_date": "2026-08-01", "report_date": "2026-06-30", "items": []})
    assert q["headline"] == "Quarterly report for the period ended 2026-06-30" and q["category"] == "filing"
    assert ns.filing_item({**r, "items": ["9.99"]})["headline"] == "Item 9.99"


def test_merge_dedupes_and_orders():
    items = [
        {"at": "2026-11-02", "headline": "Results", "source": "SEC EDGAR", "url": "https://sec/1",
         "category": "release"},
        {"at": "2026-11-02T20:00:00+00:00", "headline": "Apple beats!", "source": "provider", "url": "https://a/x?utm=1",
         "category": "news"},
        {"at": "2026-11-02T21:00:00+00:00", "headline": "Apple Beats", "source": "provider", "url": "https://b/y",
         "category": "news"},  # syndicated copy: same words
        {"at": "2026-11-03T01:00:00+00:00", "headline": "Other", "source": "provider", "url": "https://a/x",
         "category": "news"},  # same link as the second without the query
        {"at": None, "headline": "Undated", "source": "provider", "url": None, "category": "news"},
    ]  # fmt: skip
    out = ns.merge(items)
    assert [i["headline"] for i in out] == ["Results", "Apple beats!", "Undated"]


class StreamSec(FakeSec):
    pass


def test_stream_with_sec_filings(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))
    app = create_app(s)
    svc = ResearchService(s, client=StreamSec())
    with db_session() as db:
        inst = Instrument(provider="fixture", symbol="EXIC", name="Example Industrial", country="US", currency="USD")
        db.add(inst)
        db.commit()
        out = asyncio.run(ns.stream(db, app.state.market, svc, inst))
    heads = [i["headline"] for i in out["items"]]
    assert "Results of operations (earnings release)" in heads and any(h.startswith("Annual report") for h in heads)
    assert out["counts"]["release"] >= 1 and out["counts"]["filing"] >= 3
    assert any("SEC EDGAR" in x for x in out["sources"]) and "does not fetch" in out["policy"]
    dates = [i["at"][:10] for i in out["items"] if i["at"]]
    assert dates == sorted(dates, reverse=True)


def test_news_api_on_sample_data(api):
    r = api.get("/api/terminal/news", params={"symbol": "SX:AURORA"})
    assert r.status_code == 200
    out = r.json()
    assert out["items"] and all(i["source"] == "provider" for i in out["items"])
    assert all(i["url"] is None and i["publisher"] == "Sample wire (fictitious)" for i in out["items"])
    assert any("dividend" in i["headline"].lower() for i in out["items"])
    assert any("Indian listings" in n for n in out["notes"])
    ats = [i["at"] for i in out["items"]]
    assert (
        ats == sorted(ats, reverse=True) and max(ats) <= "2026-06-30T23:59:59+00:00"
    )  # nothing after the dataset date
    assert api.get("/api/terminal/news", params={"symbol": ""}).status_code == 422

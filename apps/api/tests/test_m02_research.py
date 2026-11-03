# ruff: noqa: E501
"""Research service with a fake SEC client (fictitious fixtures): configuration gate, US-only scope, CIK mapping,
filings/events with links, financials with provenance, caching and invalidation, stale fallback, malformed data,
scheduled refresh, and the HTTP endpoints."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from marketdesk.api.app import create_app
from marketdesk.config import REPO_ROOT
from marketdesk.db import db_session
from marketdesk.models import (
    Instrument,
    InstrumentIdentifier,
    MarketCacheEntry,
    ResearchCheck,
    Watchlist,
    WatchlistItem,
)
from marketdesk.providers.base import ProviderError
from marketdesk.providers.sec import SecClient, user_agent_problem
from marketdesk.services.research import ResearchService

from .conftest import Api, make_settings, migrated

FIX = REPO_ROOT / "fixtures" / "sec"


class FakeSec(SecClient):
    def __init__(self):
        super().__init__("MarketDesk tests ops@example.com")
        self.calls = {"tickers": 0, "submissions": 0, "facts": 0}
        self.sub = json.loads((FIX / "submissions_industrial.json").read_text())
        self.facts = json.loads((FIX / "companyfacts_industrial.json").read_text())
        self.fail = False

    def ticker_map(self):
        self.calls["tickers"] += 1
        return {"EXIC": (1, "Example Industrial Corp (fictitious)")}

    def submissions(self, cik):
        self.calls["submissions"] += 1
        if self.fail:
            raise ProviderError("upstream_unavailable", "SEC request failed (HTTP 503).", retryable=True)
        return self.sub

    def companyfacts(self, cik):
        self.calls["facts"] += 1
        if self.fail:
            raise ProviderError("upstream_unavailable", "SEC request failed (HTTP 503).", retryable=True)
        return self.facts


@pytest.fixture
def env(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))
    create_app(s)  # initialises the engine for db_session
    fake = FakeSec()
    svc = ResearchService(s, client=fake)
    with db_session() as db:
        us = Instrument(provider="fixture", symbol="EXIC", name="Example Industrial", country="US", currency="USD")
        india = Instrument(provider="fixture", symbol="EXIN.NS", country="IN", currency="INR")
        db.add_all([us, india])
        db.commit()
        ids = (us.id, india.id)
    return svc, fake, ids


def test_user_agent_is_required_and_validated():
    assert user_agent_problem(None) and user_agent_problem("MarketDesk") and user_agent_problem("you@example.com")
    assert user_agent_problem("MarketDesk owner@example.com") is None
    client = SecClient(None)
    with pytest.raises(ProviderError, match="SEC_USER_AGENT"):
        client.submissions(1)  # refuses before any network request


def test_not_configured_and_not_applicable(env, tmp_path):
    svc, fake, (us_id, in_id) = env
    off = ResearchService(svc.settings, client=SecClient(None))
    with db_session() as db:
        r = off.profile(db, db.get(Instrument, us_id))
        assert r["status"] == "not_configured" and "SEC_USER_AGENT" in r["reason"]
        r = svc.financials(db, db.get(Instrument, in_id), "annual")
        assert r["status"] == "not_applicable" and "not a US listing" in r["reason"]
    assert fake.calls == {"tickers": 0, "submissions": 0, "facts": 0}


def test_profile_filings_events_with_cik_mapping_and_links(env):
    svc, fake, (us_id, _) = env
    with db_session() as db:
        inst = db.get(Instrument, us_id)
        prof = svc.profile(db, inst)
        assert (
            prof["status"] == "available"
            and prof["cik"] == 1
            and prof["data"]["industry"] == "General Industrial Machinery"
        )
        ident = db.query(InstrumentIdentifier).filter_by(instrument_id=us_id, scheme="cik").one()
        assert ident.value == "1" and ident.source == "SEC company_tickers.json"
        fil = svc.filings(db, inst)["data"]
        assert [f["form"] for f in fil] == ["10-K", "8-K", "10-Q", "10-Q"]  # newest first
        assert (
            fil[0]["index_url"]
            == "https://www.sec.gov/Archives/edgar/data/1/000000000125000010/0000000001-25-000010-index.htm"
        )
        assert fil[0]["document_url"].endswith("/exic-20250930.htm")
        ev = svc.events(db, inst)["data"]
        assert ev[1]["event"] == "Results announced (8-K Item 2.02)" and ev[1]["certainty"] == "confirmed"
    assert fake.calls["tickers"] == 1 and fake.calls["submissions"] == 1  # cached across the three tabs


def test_financials_provenance_cache_and_invalidation_on_new_filing(env):
    svc, fake, (us_id, _) = env
    with db_session() as db:
        inst = db.get(Instrument, us_id)
        r = svc.financials(db, inst, "annual", price=27, price_ccy="USD")
        rev = next(x for x in r["data"]["lines"] if x["key"] == "revenue")["values"][0]
        assert rev["value"] == "1200" and rev["source_url"].endswith("0000000001-25-000010-index.htm")
        assert r["data"]["facts_url"] == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
        pe = next(x for x in r["data"]["ratios"] if x["key"] == "price_to_earnings")
        assert pe["value"] == "15"
        svc.financials(db, inst, "quarterly")  # tab switch: cached facts reused
        assert fake.calls["facts"] == 1
        check = db.query(ResearchCheck).filter_by(instrument_id=us_id, dataset="sec_companyfacts").one()
        assert check.last_success_at is not None and check.latest_accession == "0000000001-25-000010"
        # A new periodic filing appears: the facts cache key changes, so they are fetched once more.
        sub = copy.deepcopy(fake.sub)
        rec = sub["filings"]["recent"]
        for k, v in {
            "accessionNumber": "0000000001-26-000005",
            "filingDate": "2026-02-01",
            "reportDate": "2025-12-31",
            "form": "10-Q",
            "primaryDocument": "exic-20251231.htm",
            "primaryDocDescription": "10-Q",
            "items": "",
        }.items():
            rec[k].insert(0, v)
        fake.sub = sub
        db.query(MarketCacheEntry).filter(MarketCacheEntry.key == "sec:sub:1").delete()
        db.commit()
        svc.financials(db, inst, "annual")
        assert fake.calls["facts"] == 2


def test_failure_after_success_returns_stale_data_and_records_the_error(env):
    svc, fake, (us_id, _) = env
    with db_session() as db:
        inst = db.get(Instrument, us_id)
        assert svc.filings(db, inst)["status"] == "available"
        row = db.get(MarketCacheEntry, "sec:sub:1")
        row.fetched_at = datetime.now(UTC) - timedelta(days=2)  # expire the cache
        db.commit()
        fake.fail = True
        r = svc.filings(db, inst)
        assert r["status"] == "stale" and "HTTP 503" in r["reason"] and r["data"]
        check = db.query(ResearchCheck).filter_by(instrument_id=us_id, dataset="sec_submissions").one()
        assert check.last_error and check.last_success_at < check.last_checked_at


def test_malformed_company_facts_are_reported_not_hidden(env):
    svc, fake, (us_id, _) = env
    fake.facts = {"entityName": "x", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"val": "oops"}]}}}}}
    with db_session() as db:
        r = svc.financials(db, db.get(Instrument, us_id), "annual")
    assert r["status"] in ("available", "cached")
    assert next(x for x in r["data"]["lines"] if x["key"] == "revenue")["status"] == "unavailable"


def test_scheduled_refresh_checks_watchlisted_us_listings_once_per_window(env):
    svc, fake, (us_id, _) = env
    with db_session() as db:
        wl = Watchlist(name="US")
        db.add(wl)
        db.flush()
        db.add(WatchlistItem(watchlist_id=wl.id, instrument_id=us_id, position=0))
        db.commit()
        first = svc.refresh_tracked(db)
        assert first == {"checked": 1, "facts_refreshed": 1, "errors": 0}
        assert svc.refresh_tracked(db) == {"checked": 0, "facts_refreshed": 0, "errors": 0}  # within 24 h window


def test_research_endpoints(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))
    with TestClient(create_app(s)) as c:
        api = Api(c)
        r = api.get("/api/research/financials", params={"symbol": "SX:AURORA"}).json()
        assert r["status"] == "not_configured"  # SEC_USER_AGENT unset in tests
        assert api.get("/api/status").json()["research"]["sec"]["enabled"] is False
    s2 = migrated(
        make_settings(
            tmp_path / "b",
            marketdesk_env="development",
            dev_auth_bypass=True,
            sec_user_agent="MarketDesk tests ops@example.com",
        )
    )
    with TestClient(create_app(s2)) as c:
        r = Api(c).get("/api/research/filings", params={"symbol": "SX:AURORA"}).json()
        assert r["status"] == "not_applicable"  # fictitious sample listing has no country, so no SEC lookup

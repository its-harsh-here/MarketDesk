"""Terminal T3: Form 4 parsing (roles, codes in words, values), open-market summaries, DOCTYPE refusal, Yahoo
holder normalisation and cache round trip, a fake-SEC insider run, and the API on sample data."""

from __future__ import annotations

import asyncio
import copy
from datetime import date
from decimal import Decimal as D

import pandas as pd
import pytest

from marketdesk.api.app import create_app
from marketdesk.db import db_session
from marketdesk.models import Instrument
from marketdesk.providers.base import ProviderError
from marketdesk.providers.serialize import CODECS
from marketdesk.providers.yahoo import normalize_holders
from marketdesk.services import ownership as ow
from marketdesk.services.research import ResearchService

from .conftest import make_settings, migrated
from .test_m02_research import FakeSec

FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <periodOfReport>2026-10-01</periodOfReport>
  <aff10b5One>1</aff10b5One>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer>
      <officerTitle>Chief Financial Officer</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-10-01</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>150.25</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>9000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-09-30</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>I</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4_roles_codes_and_values():
    p = ow.parse_form4(FORM4)
    assert p["owners"] == [{"name": "Doe Jane", "roles": ["Chief Financial Officer"]}] and p["period"] == "2026-10-01"
    sale, award = p["transactions"]
    assert sale["action"] == "Open-market sale" and sale["acquired"] is False and sale["value"] == D("150250.00")
    assert sale["owned_after"] == D(9000) and sale["direct"] is True and sale["plan_10b5_1"] is True
    assert award["action"] == "Grant or award" and award["value"] is None and award["direct"] is False  # price 0
    assert award["security"] is None


def test_summary_counts_open_market_trades_only():
    rows = [
        {"date": "2026-10-01", "code": "S", "shares": D(1000), "value": D(150000), "insider": "A"},
        {"date": "2026-09-01", "code": "S", "shares": D(10), "value": None, "insider": "B"},
        {"date": "2026-08-01", "code": "P", "shares": D(5), "value": D(500), "insider": "A"},
        {"date": "2026-10-02", "code": "A", "shares": D(99), "value": None, "insider": "C"},
        {"date": "2025-01-01", "code": "P", "shares": D(7), "value": D(70), "insider": "A"},
    ]
    s = ow.summarize(rows, date(2026, 10, 15), 90)
    assert s["sales"] == {"count": 2, "shares": D(1010), "value": D(150000), "insiders": 2}
    assert s["buys"] == {"count": 1, "shares": D(5), "value": D(500), "insiders": 1}
    assert ow.summarize(rows, date(2026, 10, 15), 365)["buys"]["count"] == 1  # the 2025 buy is outside a year


def test_doctype_is_refused_and_xml_names_validated():
    class C(FakeSec):
        def _fetch(self, url, accept, max_bytes=0):
            return b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'

    c = C()
    with pytest.raises(ProviderError, match="DOCTYPE"):
        c.filing_xml(1, "0000000001-26-000001", "form4.xml")
    with pytest.raises(ProviderError, match="xml"):
        c.filing_xml(1, "0000000001-26-000001", "../etc/passwd")


def test_normalize_holders_and_cache_round_trip():
    major = pd.DataFrame({"Value": [0.0123, 0.61, 0.62, 5432]},
                         index=["insidersPercentHeld", "institutionsPercentHeld", "institutionsFloatPercentHeld",
                                "institutionsCount"])  # fmt: skip
    row = {"Date Reported": pd.Timestamp("2026-06-30"), "Holder": "Vanguard Group Inc", "pctHeld": 0.0912,
           "Shares": 1_350_000_000, "Value": 3.1e11, "pctChange": 0.012}  # fmt: skip
    inst = pd.DataFrame([row])
    h = normalize_holders(major, inst, None)
    assert h.insiders_pct == D("0.0123") and h.institutions_count == 5432 and h.funds == []
    r = h.institutions[0]
    assert r.holder == "Vanguard Group Inc" and r.reported == date(2026, 6, 30) and r.pct_held == D("0.0912")
    enc, dec = CODECS["holders"]
    assert dec(enc(h)) == h
    empty = normalize_holders(pd.DataFrame(), pd.DataFrame(), None)
    assert empty.insiders_pct is None and empty.institutions == []


class Form4Sec(FakeSec):
    def __init__(self):
        super().__init__()
        self.sub = copy.deepcopy(self.sub)
        rec = self.sub["filings"]["recent"]
        for k, v in {"accessionNumber": "0000000001-26-000099", "filingDate": "2026-10-03", "reportDate": "2026-10-01",
                     "form": "4", "primaryDocument": "xslF345X05/wk-form4_1.xml", "primaryDocDescription": "FORM 4",
                     "items": ""}.items():  # fmt: skip
            rec[k].insert(0, v)
        self.xml_reads = 0

    def filing_xml(self, cik, accession, name, max_bytes=1_000_000):
        assert name == "wk-form4_1.xml"  # the raw XML, not the XSL-rendered path
        self.xml_reads += 1
        return FORM4


def test_insiders_from_form4_with_per_filing_cache(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))
    create_app(s)
    fake = Form4Sec()
    svc = ResearchService(s, client=fake)
    with db_session() as db:
        inst = Instrument(provider="fixture", symbol="EXIC", name="Example Industrial", country="US", currency="USD")
        db.add(inst)
        db.commit()
        out = asyncio.run(ow.insiders(db, svc, inst, date(2026, 10, 15)))
        again = asyncio.run(ow.insiders(db, svc, inst, date(2026, 10, 15)))
    assert out["filings_read"] == 1 and fake.xml_reads == 1 and again["transactions"] == out["transactions"]
    t = out["transactions"][0]
    assert (
        t["insider"] == "Doe Jane" and t["roles"] == ["Chief Financial Officer"] and t["action"] == "Open-market sale"
    )
    assert t["value"] == D("150250.00") and "0000000001-26-000099" in t["url"]
    assert out["summary"][0]["sales"]["count"] == 1 and out["summary"][0]["buys"]["count"] == 0


def test_ownership_api_on_sample_data(api):
    out = api.get("/api/terminal/ownership", params={"symbol": "SX:AURORA"}).json()
    h = out["holders"]
    assert h["source"] == "Sample holders (fictitious)" and h["institutions"] and h["funds"]
    assert all("(fictitious)" in r["holder"] for r in h["institutions"] + h["funds"])
    assert 0 < float(h["insiders_pct"]) < 1 and out["insiders"]["status"] == "not_applicable"
    assert any("shareholding pattern" in n for n in out["notes"])
    us = api.get("/api/terminal/ownership", params={"symbol": "SX:HALCYON"}).json()
    assert us["insiders"]["status"] == "not_applicable"  # the sample US-style listing has no country

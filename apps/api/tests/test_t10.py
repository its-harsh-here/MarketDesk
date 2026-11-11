"""Terminal T10: customer-concentration and supplier-dependence sentences quoted from an annual report."""

from __future__ import annotations

from marketdesk.services import relationships as rel

TEXT = """Item 1. Business. We sell to retailers worldwide. For fiscal 2025, Walmart Inc. accounted for 18% of our net
sales and Target Corporation represented approximately 11.5% of net sales. No other customer accounted for more than
10% of revenue. We rely on a single supplier, Example Foundry Ltd., for our custom processors. Our suppliers ship
goods by sea. Customer A accounted for 14% of total revenue in 2025. This report contains forward-looking statements
about customers that accounted for 30% of sales. Revenue grew 12% year over year.
Revenue from Asia accounted for 22% of net sales. The Company relies on suppliers to adhere to its supplier code of
conduct."""


def test_extract_customers_and_suppliers():
    out = rel.extract(TEXT)
    quotes = [c["quote"] for c in out["customers"]]
    assert any(q.startswith("For fiscal 2025, Walmart Inc.") for q in quotes)
    walmart = next(c for c in out["customers"] if "Walmart" in c["quote"])
    assert walmart["named"] == [
        {"name": "Walmart Inc.", "share_pct": "18"},
        {"name": "Target Corporation", "share_pct": "11.5"},
    ]
    assert any(c["named"] == [{"name": "Customer A", "share_pct": "14"}] for c in out["customers"])
    assert any("No other customer" in q for q in quotes)  # kept as context, without a name
    assert not any("forward-looking" in q for q in quotes) and not any(q.startswith("Revenue grew") for q in quotes)
    assert not any("Asia" in q for q in quotes)  # a region, not a customer
    assert [s["quote"] for s in out["suppliers"]] == [
        "We rely on a single supplier, Example Foundry Ltd., for our custom processors."
    ]  # "Our suppliers ship goods by sea." has no dependence word


def test_relationships_api_is_explained_outside_sec(api):
    out = api.get("/api/terminal/relationships", params={"symbol": "SX:AURORA"}).json()
    assert out["status"] == "not_applicable" and out["confidence"] == "low"


def test_relationships_from_the_latest_10k_cached_per_filing(tmp_path):
    import asyncio

    from marketdesk.api.app import create_app
    from marketdesk.db import db_session
    from marketdesk.models import Instrument
    from marketdesk.services.research import ResearchService

    from .conftest import make_settings, migrated
    from .test_m02_research import FakeSec

    class Sec(FakeSec):
        reads = 0

        def filing_files(self, cik, accession):
            return [{"name": "exic-20250930.htm"}]

        def document_text(self, cik, accession, doc, max_chars, max_bytes):
            Sec.reads += 1
            assert doc == "exic-20250930.htm"
            return TEXT

    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))
    create_app(s)
    svc = ResearchService(s, client=Sec())
    with db_session() as db:
        inst = Instrument(provider="fixture", symbol="EXIC", name="Example Industrial", country="US", currency="USD")
        db.add(inst)
        db.commit()
        out = asyncio.run(rel.relationships(db, svc, inst))
        again = asyncio.run(rel.relationships(db, svc, inst))
    assert out["status"] == "available" and out["filing"]["form"] == "10-K" and out["filing"]["filed"] == "2025-11-01"
    assert out["filing"]["url"].endswith("exic-20250930.htm") and len(out["suppliers"]) == 1
    assert Sec.reads == 1 and again["customers"] == out["customers"]  # read once per filing

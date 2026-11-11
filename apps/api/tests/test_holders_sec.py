"""Holders from SEC when Yahoo is refused: structured Schedule 13G/13D parsing (namespaced XML), one row per holder
(newest filing wins, exits below 5% marked), insiders' latest direct holdings from Form 4 rows, and relationship
rules that recognise "single or limited sources" / "outsourcing partners" wording."""

from __future__ import annotations

from decimal import Decimal as D

from marketdesk.services import ownership as own
from marketdesk.services.relationships import extract

G = """<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g" xmlns:com="http://www.sec.gov/edgar/common">
 <formData>
  <coverPageHeader><securitiesClassTitle>Common Stock</securitiesClassTitle>
   <eventDateRequiresFilingThisStatement>2026-03-31</eventDateRequiresFilingThisStatement></coverPageHeader>
  <coverPageHeaderReportingPersonDetails>
   <reportingPersonName>Big Index Group, Inc.</reportingPersonName>
   <reportingPersonBeneficiallyOwnedAggregateNumberOfShares>1,250,000,000</reportingPersonBeneficiallyOwnedAggregateNumberOfShares>
   <classPercent>8.4</classPercent><typeOfReportingPerson>HC</typeOfReportingPerson>
  </coverPageHeaderReportingPersonDetails>
  <coverPageHeaderReportingPersonDetails>
   <reportingPersonName>Big Index Fund Trust</reportingPersonName>
   <reportingPersonBeneficiallyOwnedAggregateNumberOfShares>400000000</reportingPersonBeneficiallyOwnedAggregateNumberOfShares>
   <classPercent>2.7</classPercent><typeOfReportingPerson>IV</typeOfReportingPerson>
  </coverPageHeaderReportingPersonDetails>
 </formData>
</edgarSubmission>"""

D13 = """<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D"><formData>
 <coverPageHeader><dateOfEvent>01/15/2026</dateOfEvent></coverPageHeader>
 <reportingPersons><reportingPersonInfo><reportingPersonName>Activist Partners LP</reportingPersonName>
  <aggregateAmountOwned>52000000</aggregateAmountOwned><percentOfClass>6.1</percentOfClass>
  <typeOfReportingPerson>PN</typeOfReportingPerson></reportingPersonInfo></reportingPersons>
</formData></edgarSubmission>"""


def test_parse_schedule_13g_and_13d():
    g = own.parse_schedule13(G)
    assert g["kind"] == "13G" and g["event_date"] == "2026-03-31" and g["security"] == "Common Stock"
    assert [p["name"] for p in g["persons"]] == ["Big Index Group, Inc.", "Big Index Fund Trust"]
    assert g["persons"][0]["shares"] == D(1_250_000_000) and g["persons"][0]["percent"] == D("8.4")
    d = own.parse_schedule13(D13)
    assert d["kind"] == "13D" and d["persons"][0] == {"name": "Activist Partners LP", "shares": D(52_000_000),
                                                      "percent": D("6.1"), "type": "PN"}  # fmt: skip


def test_major_rows_latest_per_holder_and_exits():
    def f(date, acc):
        return {"filing_date": date, "form": "SCHEDULE 13G/A", "index_url": f"https://sec/{acc}", "accession": acc}

    newer = own._jsonable_13(own.parse_schedule13(G))
    older = own._jsonable_13(own.parse_schedule13(G.replace("8.4", "7.9")))
    exit_ = own._jsonable_13(own.parse_schedule13(D13.replace("6.1", "4.2")))
    rows = own.major_rows([f("2025-02-01", "a"), f("2026-04-29", "b"), f("2026-01-20", "c"), f("2026-02-01", "d")],
                          [older, newer, exit_, {"error": "unreadable"}])  # fmt: skip
    assert [r["holder"] for r in rows] == ["Big Index Group, Inc.", "Activist Partners LP"]
    top = rows[0]
    assert top["percent"] == D("8.4") and top["filed"] == "2026-04-29" and top["persons"] == 2
    assert not top["below_threshold"]
    assert rows[1]["below_threshold"] and rows[1]["kind"] == "13D"


def test_insider_holdings_latest_direct_position():
    rows = [
        {"insider": "A", "roles": ["CEO"], "date": "2026-10-01", "filed": "2026-10-03", "direct": True,
         "owned_after": D(900), "url": "u1"},
        {"insider": "A", "roles": ["CEO"], "date": "2026-11-01", "filed": "2026-11-03", "direct": True,
         "owned_after": D(800), "url": "u2"},
        {"insider": "A", "roles": ["CEO"], "date": "2026-11-05", "filed": "2026-11-06", "direct": False,
         "owned_after": D(5000), "url": "u3"},  # indirect holding is not the insider's own position
        {"insider": "B", "roles": [], "date": "2026-09-01", "filed": "2026-09-02", "direct": True,
         "owned_after": D(2000), "url": "u4"},
    ]  # fmt: skip
    h = own.insider_holdings(rows)
    assert [(x["insider"], x["shares"], x["as_of"]) for x in h] == [("B", D(2000), "2026-09-01"),
                                                                   ("A", D(800), "2026-11-01")]  # fmt: skip


def test_relationship_rules_cover_limited_sources_and_outsourcing():
    text = (
        "Although most components essential to the Company's business are generally available from multiple "
        "sources, certain components are currently obtained from single or limited sources. Substantially all of "
        "the Company's hardware products are manufactured by outsourcing partners located primarily in Asia. "
        "The Company had one customer that individually represented 10% or more of total trade receivables. "
        "Revenue from Asia accounted for 12% of net sales in the year."
    )
    out = extract(text)
    assert len(out["suppliers"]) == 2 and len(out["customers"]) == 1
    assert "trade receivables" in out["customers"][0]["quote"]

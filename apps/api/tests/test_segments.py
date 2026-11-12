"""Segment / product / geography revenue from a 10-K's XBRL instance (terminal roadmap T2 stretch)."""

from datetime import date
from decimal import Decimal as D

import pytest

from marketdesk.config import REPO_ROOT
from marketdesk.db import db_session
from marketdesk.models import Instrument
from marketdesk.services import segments as seg

from .test_m02_research import FakeSec, env  # noqa: F401 - fixture

FIX = REPO_ROOT / "fixtures" / "sec"


def test_annual_single_dimension_facts_by_axis_with_filer_labels():
    out = seg.parse_instance((FIX / "segments_instance.xml").read_bytes())
    axes = {a["axis"]: a for a in out["axes"]}
    segs = {m["member"]: m for m in axes["StatementBusinessSegmentsAxis"]["members"]}
    # ASU 2023-07 "operating segments" dimension is ignored; the quarter-long Valves context is not annual
    assert segs["exic:PumpsSegmentMember"]["revenue"] == {
        date(2025, 9, 30): D(700000000),
        date(2024, 9, 30): D(640000000),
    }
    assert segs["exic:PumpsSegmentMember"]["operating_income"] == {date(2025, 9, 30): D(120000000)}
    assert segs["exic:ValvesSegmentMember"]["revenue"] == {date(2025, 9, 30): D(300000000)}
    # a context with two real dimensions (product × country) is a cross-cut, not a breakdown: left out
    assert [m["revenue"] for m in axes["ProductOrServiceAxis"]["members"]] == [{date(2025, 9, 30): D(150000000)}]
    assert "StatementGeographicalAxis" not in axes and out["currency"] == "USD"
    labels = seg.parse_labels(
        (FIX / "segments_lab.xml").read_bytes(), {"exic:PumpsSegmentMember", "exic:ValvesSegmentMember"}
    )
    assert labels == {"exic:PumpsSegmentMember": "Pumps & Flow", "exic:ValvesSegmentMember": "Valves"}
    assert seg.member_label("aapl:WearablesHomeandAccessoriesMember") == "Wearables Homeand Accessories"
    assert seg.member_label("aapl:GreaterChinaSegmentMember") == "Greater China"


def test_doctype_is_refused():
    with pytest.raises(ValueError, match="DOCTYPE"):
        seg.parse_instance(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><xbrl/>')


class FakeSecSegments(FakeSec):
    def filing_files(self, cik, accession):
        return [{"name": "exic-20250930_htm.xml"}, {"name": "exic-20250930_lab.xml"}, {"name": "exic-20250930.htm"}]

    def filing_bytes(self, cik, accession, name, max_bytes=40_000_000):
        self.calls["bytes"] = self.calls.get("bytes", 0) + 1
        return (FIX / ("segments_lab.xml" if name.endswith("_lab.xml") else "segments_instance.xml")).read_bytes()


def test_service_reads_the_latest_annual_report_once(env):  # noqa: F811
    svc, _, (us_id, _) = env
    svc.client = FakeSecSegments()
    with db_session() as db:
        inst = db.get(Instrument, us_id)
        r = svc.segments(db, inst)
        assert r["status"] == "available", r
        d = r["data"]
        assert (
            d["form"] == "10-K"
            and d["accession"] == "0000000001-25-000010"
            and d["fiscal_year_ends"][0] == "2025-09-30"
        )
        pumps = d["axes"][0]["members"][0]
        assert pumps["label"] == "Pumps & Flow" and pumps["revenue"]["2025-09-30"] == "700000000"
        assert svc.segments(db, inst)["status"] == "cached" and svc.client.calls["bytes"] == 2  # instance + labels once

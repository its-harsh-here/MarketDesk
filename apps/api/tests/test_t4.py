"""Terminal T4: earnings and corporate events — hand vectors for proxy meeting dates, buyback mentions, reported-figure
history with year-on-year change and past/upcoming splitting; a fake-SEC run of the per-security builder (US) with
document scans cached per filing; the API on sample data (India deadline, dividends, universe window, history)."""

from __future__ import annotations

import asyncio
import copy
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from marketdesk.api.app import create_app
from marketdesk.db import db_session
from marketdesk.models import Instrument
from marketdesk.services import events as ev
from marketdesk.services.research import ResearchService

from .conftest import make_settings, migrated
from .test_m02_research import FakeSec

PROXY = (
    "NOTICE OF 2026 ANNUAL MEETING OF STOCKHOLDERS. The Annual Meeting of Stockholders of Example Industrial Corp "
    "will be held on Thursday, {when}, at 9:00 a.m. Eastern Time, in a virtual-only format. The record date was "
    "{record}. Our 2025 annual meeting took place on February 20, 2025."
)
RELEASE = (
    "Example Industrial Corp reported third-quarter revenue of $300 million. During the quarter, the Company "
    "repurchased 1.2 million shares for $45 million under its $500 million share repurchase program authorized by "
    "the Board. This press release contains forward-looking statements, including statements about future "
    "repurchases under the program. Net income was $40 million. Buyback. The Board also declared a dividend."
)


def long_date(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


# --------------------------------------------------------------------- pure
def test_meeting_date_is_quoted_and_must_be_near_the_filing():
    filed = date(2026, 1, 15)
    text = PROXY.format(when="February 26, 2026", record="December 29, 2025")
    found = ev.meeting_date(text, filed)
    assert found is not None
    d, quote = found
    assert d == date(2026, 2, 26) and "February 26, 2026" in quote and len(quote) <= 320
    # a date far from the filing is a stray reference, not the meeting
    assert ev.meeting_date(PROXY.format(when="June 1, 2021", record="May 1, 2021"), filed) is None
    assert ev.meeting_date("No notice here. Just a date: March 3, 2026.", filed) is None
    # case and zero-width characters (common in EDGAR HTML) do not matter
    assert ev.meeting_date(text.upper().replace("FEBRUARY", "FEBRU\u200bARY"), filed)[0] == date(2026, 2, 26)
    assert ev.parse_month_date("february 30, 2026") is None and ev.parse_month_date("Smarch 1, 2026") is None


def test_buyback_sentences_quote_mentions_but_skip_boilerplate():
    out = ev.buyback_sentences(RELEASE)
    assert len(out) == 1 and out[0].startswith("During the quarter") and "$500 million" in out[0]
    many = " ".join(f"The Company repurchased {i} million shares under its program in month {i}." for i in range(6))
    assert len(ev.buyback_sentences(many, limit=3)) == 3
    assert ev.buyback_sentences("Nothing relevant was said. Revenue grew.") == []


def test_history_rows_report_figures_with_year_on_year_change():
    def val(end, value, **kw):
        return {"value": value, "end": end, "start": None, "unit": "USD", "form": "10-Q", "filed": "x",
                "accession": "a", "source_url": "u", "restated": False, **kw}  # fmt: skip

    st = {
        "lines": [
            {
                "key": "revenue",
                "values": [
                    val(date(2026, 6, 30), "330"),
                    val(date(2025, 6, 30), "300"),
                    val(date(2024, 6, 30), "250", restated=True),
                ],
            },  # fmt: skip
            {"key": "net_income", "values": [val(date(2026, 6, 30), "-5"), val(date(2025, 6, 30), "-10")]},
            {"key": "eps_diluted", "values": [val(date(2026, 6, 30), "1.5", unit="USD/shares")]},
        ]
    }
    rows = ev.history_rows(st)
    assert [r["period_end"] for r in rows] == ["2026-06-30", "2025-06-30", "2024-06-30"]
    top = rows[0]
    assert top["revenue"]["value"] == D(330) and top["revenue"]["yoy_pct"] == D(10)
    assert top["net_income"]["yoy_pct"] is None  # a negative base has no meaningful growth rate
    assert top["eps_diluted"]["unit"] == "USD/shares" and top["eps_diluted"]["yoy_pct"] is None
    assert rows[1]["revenue"]["yoy_pct"] == D(20) and rows[2]["revenue"]["restated"] is True
    assert rows[2]["net_income"] is None and rows[2]["revenue"]["yoy_pct"] is None
    assert ev.yoy(D(5), D(0)) is None and ev.yoy(None, D(1)) is None


def test_split_events_dedupes_and_orders_around_today():
    today = date(2026, 11, 10)
    rows = [
        ev.event(date(2026, 11, 10), "results", "Next results (estimate)", "estimated", "s"),
        ev.event("2026-12-01", "dividend", "Dividend 1 per share", "confirmed", "s"),
        ev.event("2026-01-05", "report", "10-K filed", "confirmed", "s"),
        ev.event("2026-01-05", "report", "10-K filed", "confirmed", "s"),  # duplicate
        ev.event("2026-06-01", "proxy", "Proxy statement filed (DEF 14A)", "confirmed", "s"),
    ]
    out = ev.split_events(rows, today)
    assert [e["date"] for e in out["upcoming"]] == ["2026-11-10", "2026-12-01"]  # today counts as upcoming
    assert [e["date"] for e in out["past"]] == ["2026-06-01", "2026-01-05"]


def test_results_events_distinguish_deadline_from_estimate():
    deadline = {"past": [{"date": "2026-09-30", "kind": "Latest reported quarter end"}], "source": "fx",
                "next": {"date": "2026-11-14", "basis": "deadline", "explanation": "SEBI"}}  # fmt: skip
    rows = ev._results_events(deadline, "SX:A")
    assert rows[1]["status"] == "deadline" and "SEBI" in rows[1]["label"] and rows[1]["symbol"] == "SX:A"
    est = {"past": [], "source": "SEC", "next": {"date": "2027-01-28", "basis": "cadence", "window": 5}}
    r = ev._results_events(est)[0]
    assert r["status"] == "estimated" and r["window"] == 5 and "symbol" not in r
    assert ev.jsonable({"a": D("1.23456"), "d": date(2026, 1, 1), "l": [D(2)]}) == {
        "a": "1.2346", "d": "2026-01-01", "l": ["2.0000"]}  # fmt: skip


# --------------------------------------------------------------------- builder with a fake SEC
class EventsSec(FakeSec):
    """Adds filing documents: a proxy whose notice states the meeting date, and a results release that mentions a
    buyback programme."""

    def __init__(self, filed: date, meeting: date):
        super().__init__()
        self.docs = 0
        self.meeting = meeting
        self.sub = copy.deepcopy(self.sub)
        rec = self.sub["filings"]["recent"]
        for k, v in {
            "accessionNumber": "0000000001-26-000005", "filingDate": filed.isoformat(), "reportDate": "",
            "form": "DEF 14A", "primaryDocument": "exic-def14a.htm", "primaryDocDescription": "DEF 14A", "items": "",
        }.items():  # fmt: skip
            rec[k].insert(0, v)

    def filing_files(self, cik, accession):
        if accession.endswith("000005"):
            return [{"name": "exic-def14a.htm"}, {"name": "R1.htm"}]
        return [{"name": "exic-8k.htm"}, {"name": "exic-ex991.htm"}]

    def document_text(self, cik, accession, doc, max_chars, max_bytes):
        self.docs += 1
        if doc == "exic-def14a.htm":
            return PROXY.format(when=long_date(self.meeting), record=long_date(self.meeting - timedelta(days=50)))
        assert doc == "exic-ex991.htm"  # releases: exhibit 99, not the cover
        return RELEASE


@pytest.fixture
def us_env(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))
    app = create_app(s)
    today = date.today()
    fake = EventsSec(filed=today - timedelta(days=10), meeting=today + timedelta(days=40))
    svc = ResearchService(s, client=fake)
    with db_session() as db:
        us = Instrument(provider="fixture", symbol="EXIC", name="Example Industrial", country="US", currency="USD")
        db.add(us)
        db.commit()
        uid = us.id
    return app.state.market, svc, fake, uid


def test_security_events_from_sec_filings_are_cached_per_document(us_env):
    market, svc, fake, uid = us_env
    with db_session() as db:
        inst = db.get(Instrument, uid)
        out = asyncio.run(ev.security_events(db, market, svc, inst))
        kinds = {e["kind"] for e in out["past"] + out["upcoming"]}
        assert kinds >= {"results", "report", "proxy", "meeting", "buyback"}
        meeting = next(e for e in out["upcoming"] if e["kind"] == "meeting")
        assert meeting["date"] == fake.meeting.isoformat() and "quoted from the proxy" in meeting["source"]
        assert long_date(fake.meeting) in meeting["quote"]
        bb = next(e for e in out["past"] if e["kind"] == "buyback")
        assert bb["status"] == "mention" and bb["quote"].startswith("During the quarter") and bb["url"].endswith(".htm")
        reports = [e for e in out["past"] if e["kind"] == "report"]
        assert {r["label"] for r in reports} == {"10-K filed", "10-Q filed"} and all(r["period"] for r in reports)
        assert any("Too few regular results filings" in n for n in out["notes"])  # one 8-K: no cadence estimate
        assert out["consensus"]["status"] == "licensed" and any("SEC EDGAR" in s for s in out["sources"])
        assert fake.docs == 2  # one proxy, one release
        again = asyncio.run(ev.security_events(db, market, svc, inst))
        assert fake.docs == 2 and again["upcoming"] == out["upcoming"]  # scans are cached per accession
        hist = asyncio.run(ev.earnings_history(db, market, svc, inst))
        assert hist["official"] is True and hist["period"] == "quarterly" and hist["rows"]
        assert {"revenue", "net_income", "eps_diluted", "period_end"} <= set(hist["rows"][0])
        assert "SEC EDGAR" in hist["source"] and hist["consensus"]["status"] == "licensed"


# --------------------------------------------------------------------- API on sample data
def test_events_api_on_sample_data(api):
    r = api.get("/api/terminal/events", params={"symbol": "SX:AURORA"})
    assert r.status_code == 200
    out = r.json()
    nxt = [e for e in out["upcoming"] if e["kind"] == "results"]
    assert nxt and nxt[0]["status"] == "deadline" and "SEBI" in nxt[0]["label"]
    divs = [e for e in out["past"] if e["kind"] == "dividend"]
    assert divs and divs[0]["value"] == "4.00" and divs[0]["source"] == "fixture corporate actions"
    assert all(e["date"] < date.today().isoformat() for e in out["past"])
    assert any("Indian listings" in n for n in out["notes"]) and out["consensus"]["status"] == "licensed"
    us = api.get("/api/terminal/events", params={"symbol": "SX:HALCYON"}).json()
    # the sample US-style listing carries no country, so neither SEC nor SEBI applies and the view says so
    assert any("neither applies" in n for n in us["notes"]) and not any(e["kind"] == "proxy" for e in us["past"])
    assert api.get("/api/terminal/events", params={"symbol": "SX:NOPE"}).status_code == 422


def test_universe_events_api_windows_and_validates(api):
    wl = api.post("/api/watchlists", json={"name": "T4"}).json()["id"]
    for s in ("SX:AURORA", "SX:HALCYON", "SX:SX50"):
        api.post(f"/api/watchlists/{wl}/items", json={"symbol": s})
    r = api.get("/api/terminal/events/universe", params={"universe": f"watchlist:{wl}", "ahead": 180, "back": 90})
    assert r.status_code == 200
    out = r.json()
    assert out["universe"]["members"] == 2 and out["universe"]["scanned"] == 2  # the index is left out
    assert out["window"]["ahead_days"] == 180 and out["failed"] == []
    syms = {e["symbol"] for e in out["upcoming"]}
    assert "SX:AURORA" in syms and all("symbol" in e for e in out["past"] + out["upcoming"])
    assert all(out["window"]["from"] <= e["date"] <= out["window"]["to"] for e in out["past"] + out["upcoming"])
    assert "No consensus" in out["note"]
    assert api.get("/api/terminal/events/universe", params={"ahead": 3}).status_code == 422
    assert api.get("/api/terminal/events/universe", params={"universe": "bogus"}).status_code == 422


def test_earnings_history_api_on_sample_data(api):
    out = api.get("/api/terminal/earnings-history", params={"symbol": "SX:AURORA"}).json()
    assert out["official"] is False and out["period"] == "annual" and "unofficial" in out["source"]
    rows = out["rows"]
    assert len(rows) >= 2 and rows[0]["period_end"] > rows[1]["period_end"]
    assert rows[0]["revenue"]["yoy_pct"] is not None and "eps_diluted" not in rows[0]
    assert float(rows[0]["revenue"]["yoy_pct"]) == pytest.approx(
        (float(rows[0]["revenue"]["value"]) / float(rows[1]["revenue"]["value"]) - 1) * 100, abs=1e-3
    )
    assert out["consensus"]["status"] == "licensed" and out["notes"]

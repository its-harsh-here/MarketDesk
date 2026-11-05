"""M07: earnings calendar (estimates and deadlines, never invented announcements), period changes that never mix
quarters with year-to-date, quoted filing changes and guidance, results reminders, and the AI brief task."""

from __future__ import annotations

from datetime import date, timedelta

from marketdesk.services import earnings as er


def test_cadence_estimate_needs_a_regular_history():
    ds = [date(2025, 2, 6), date(2025, 5, 7), date(2025, 8, 6), date(2025, 11, 5)]
    est = er.cadence_estimate(ds, date(2025, 11, 20))
    assert est["basis"] == "estimated" and est["date"] == (date(2025, 11, 5) + timedelta(days=91)).isoformat()
    assert "not announced" in est["explanation"] and len(est["window"]) == 2
    assert er.cadence_estimate(ds[:2], date(2025, 11, 20)) is None
    assert er.cadence_estimate([date(2024, 1, 1), date(2024, 8, 1), date(2025, 3, 1)], date(2025, 4, 1)) is None
    late = er.cadence_estimate(ds, date(2026, 6, 1))  # rolled forward, never in the past
    assert date.fromisoformat(late["date"]) + timedelta(days=7) >= date(2026, 6, 1)


def test_sebi_deadlines():
    assert er.quarter_end_after(date(2026, 3, 31)) == date(2026, 6, 30)
    assert er.quarter_end_after(date(2025, 12, 31)) == date(2026, 3, 31)
    d = er.sebi_deadline(date(2026, 3, 31), date(2026, 3, 31), date(2026, 7, 1))
    assert (d["date"], d["period_end"], d["period"], d["basis"]) == ("2026-08-14", "2026-06-30", "quarter", "deadline")
    fy = er.sebi_deadline(date(2025, 12, 31), date(2025, 3, 31), date(2026, 1, 10))
    assert (fy["date"], fy["period"]) == ("2026-05-30", "financial year")  # 60 days after a March year end
    rolled = er.sebi_deadline(date(2026, 3, 31), date(2026, 3, 31), date(2026, 8, 20))
    assert rolled["date"] == "2026-11-14" and "not an announced one" in rolled["explanation"]


def fact(end, value, restated=False):
    return {
        "value": str(value),
        "unit": "USD",
        "start": None,
        "end": end,
        "form": "10-Q",
        "filed": end,
        "accession": f"acc-{end}",
        "restated": restated,
        "source_url": f"https://sec.example/{end}",
        "prior": [],
    }


def test_period_changes_qoq_yoy_and_margins():
    st = {
        "period_ends": ["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"],
        "lines": [
            {
                "key": "revenue",
                "label": "Revenue",
                "status": "available",
                "values": [fact("2026-03-31", 1200), fact("2025-12-31", 1000), fact("2025-03-31", 800, restated=True)],
            },
            {
                "key": "net_income",
                "label": "Net income",
                "status": "available",
                "values": [fact("2026-03-31", 120), fact("2025-12-31", 150), fact("2025-03-31", 40)],
            },
            {"key": "segment_noise", "label": "x", "status": "available", "values": []},
        ],
    }
    qoq = {r["key"]: r for r in er.compare_periods(st, "qoq")}
    assert qoq["revenue"]["prior_end"] == "2025-12-31" and qoq["revenue"]["change_pct"] == "20.00"
    assert qoq["net_margin"]["latest_pct"] == "10.00" and qoq["net_margin"]["change_pp"] == "-5.00"
    yoy = {r["key"]: r for r in er.compare_periods(st, "yoy")}
    assert yoy["revenue"]["prior_end"] == "2025-03-31" and yoy["revenue"]["change_pct"] == "50.00"
    assert yoy["revenue"]["prior"]["restated"] is True and yoy["revenue"]["latest"]["source_url"].endswith("2026-03-31")
    assert "segment_noise" not in qoq
    no_year_ago = {"period_ends": ["2026-03-31", "2025-12-31"], "lines": st["lines"][:1]}
    assert er.compare_periods(no_year_ago, "yoy")[0]["prior"] is None  # never substitutes another period


RISK_TOC = "Table of contents\nItem 1A. Risk Factors 12\nItem 2. Properties 30\n"


def doc(paras):
    body = "\n".join(paras)
    return f"{RISK_TOC}\nItem 1A. Risk Factors\n{body}\nItem 1B. Unresolved Staff Comments\nNone."


P = [
    "Our revenue depends on a small number of large utility customers, and the loss of any of them could reduce sales.",
    "We are subject to extensive regulation by the Nuclear Regulatory Commission, which may delay our product "
    "approvals.",
    "Supply chain disruptions for specialised components could increase our costs and delay deliveries to customers.",
]


def test_risk_factor_changes_are_quoted():
    old_sec = er.risk_section(doc(P))
    assert old_sec is not None and "Properties 30" not in old_sec  # the table of contents entry is skipped
    new = [
        P[0],
        P[1].replace("may delay", "could materially delay"),
        "Rising interest rates may make it harder for customers to finance new power plants over the next decade.",
    ]
    d = er.diff_paragraphs(er.paragraphs(old_sec), er.paragraphs(er.risk_section(doc(new))))
    assert d["counts"] == {"old": 3, "new": 3, "added": 1, "removed": 1, "reworded": 1}
    assert d["added"][0].startswith("Rising interest rates") and d["removed"][0].startswith("Supply chain")
    assert "could materially delay" in d["reworded"][0]["after"] and d["reworded"][0]["similarity"] >= 0.6
    assert er.risk_section("no such section here") is None


def test_guidance_sentences():
    text = (
        "Revenue rose 12% to $410 million. The Company expects full-year revenue of $1.6 billion to $1.7 billion. "
        "This release contains forward-looking statements, and the Company expects 2027 results to vary. "
        "We continue to invest in research. Outlook: second-quarter margin of about 31%."
    )
    s = er.guidance_sentences(text)
    assert s == [
        "The Company expects full-year revenue of $1.6 billion to $1.7 billion.",
        "Outlook: second-quarter margin of about 31%.",
    ]


def test_earnings_api_on_sample_data(api):
    a = api.get("/api/earnings/SX:AURORA").json()
    cal = a["calendar"]
    assert cal["next"]["basis"] == "deadline" and "SEBI" in cal["next"]["explanation"]
    assert date.fromisoformat(cal["next"]["date"]) >= date.today() - timedelta(days=1)
    assert cal["past"][0]["kind"] == "Latest reported quarter end"
    ch = a["changes"]
    assert ch["available"] and ch["qoq"] == [] and {r["key"] for r in ch["fy"]} >= {"revenue", "net_income"}
    rev = next(r for r in ch["fy"] if r["key"] == "revenue")
    assert 6 < float(rev["change_pct"]) < 8
    us = api.get("/api/earnings/SX:HALCYON").json()["calendar"]
    assert us["next"] is None and us["note"]
    fc = api.get("/api/earnings/SX:AURORA/filing-changes", params={"form": "10-K"}).json()
    assert fc["available"] is False and "SEC" in fc["reason"]
    assert api.get("/api/earnings/SX:AURORA/guidance").json()["available"] is False
    wl = api.post("/api/watchlists", json={"name": "E"}).json()["id"]
    for s in ("SX:AURORA", "SX:HALCYON", "SX:SX50"):
        api.post(f"/api/watchlists/{wl}/items", json={"symbol": s})
    uni = api.get("/api/earnings/calendar").json()
    assert [r["symbol"] for r in uni["rows"]] == ["SX:AURORA", "SX:HALCYON"]  # dated first; the index is left out
    assert "none is an announced date" in uni["note"]


def test_results_reminder_fires_once(api, app):
    from marketdesk.db import db_session
    from marketdesk.models import Alert, AlertEvent
    from marketdesk.services.alerts import evaluate_earnings

    bad = api.post("/api/alerts", json={"symbol": "SX:AURORA", "rule": "EARNINGS", "params": {"days_before": 45}})
    assert bad.status_code == 422  # beyond 30 days
    r = api.post("/api/alerts", json={"symbol": "SX:AURORA", "rule": "EARNINGS", "params": {"days_before": 5}})
    assert r.status_code == 201, r.text
    assert "5 day(s)" in r.json()["description"]
    cal = {"next": {"date": "2026-08-14", "basis": "deadline", "explanation": er.SEBI_RULE}}
    with db_session() as db:
        alert = db.get(Alert, r.json()["id"])
        assert evaluate_earnings(db, alert, cal, date(2026, 8, 1)) is None  # 13 days early
        ev = evaluate_earnings(db, alert, cal, date(2026, 8, 10))
        assert ev is not None and "deadline for results 2026-08-14" in ev.explanation
        assert evaluate_earnings(db, alert, cal, date(2026, 8, 11)) is None  # once per date
        assert db.query(AlertEvent).count() == 1


def test_brief_is_an_ai_task(api):
    r = api.post("/api/ai/answers", json={"kind": "brief", "symbols": ["SX:AURORA"]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_disabled"  # accepted kind; AI is off in tests
    from marketdesk.services.analyst import TASKS

    assert "Bull case" in TASKS["brief"] and "price targets" in TASKS["brief"]


def test_risk_section_fallbacks():
    body = "\n".join(P)
    zw = f"Item 1​A. Risk Factors\n{body}\nItem 1B. Unresolved Staff Comments"
    assert er.risk_section(zw) is not None  # zero-width characters inside the heading
    plain = f"RISK FACTORS\n{body}\nITEM 2. PROPERTIES\nOffices."
    sec = er.risk_section(plain)
    assert sec is not None and "Offices" not in sec  # no item number: the longest Risk Factors section
    d = er.risk_diagnostics("Annual report without the section")
    assert d["risk_factor_mentions"] == 0 and d["chars"] > 0


def test_periodic_reports_use_the_primary_document():
    from marketdesk.services.analyst import _pick_document

    files = [{"name": "a311-302spaccertceojh1.htm"}, {"name": "smr-20251231.htm"}, {"name": "R1.htm"}]
    filing = {"form": "10-K", "document_url": "https://www.sec.gov/Archives/edgar/data/1/2/smr-20251231.htm"}
    assert _pick_document(files, "10-K", filing) == "smr-20251231.htm"  # not the certification exhibit
    release = [{"name": "smr-ex991.htm"}, {"name": "smr-8k.htm"}]
    assert _pick_document(release, "8-K", {"document_url": ".../smr-8k.htm"}) == "smr-ex991.htm"  # releases: exhibit 99


def test_risk_diff_stays_fast_on_annual_report_sized_sections():
    """Real 10-K Item 1A sections have hundreds of long paragraphs; the comparison must stay well under a second
    (character-level comparison of every pair took minutes on the live server)."""
    import random
    import time

    rnd = random.Random(3)
    vocab = [f"w{i}" for i in range(400)]

    def para():
        return " ".join(rnd.choice(vocab) for _ in range(150))

    old = [para() for _ in range(250)]
    new = [para() for _ in range(250)]  # nothing in common
    t = time.perf_counter()
    d = er.diff_paragraphs(old, new)
    assert time.perf_counter() - t < 5
    assert d["counts"]["reworded"] == 0 and d["counts"]["added"] == 250
    edited = [p.replace(p.split()[3], "changed", 1) for p in old[:40]] + old[40:]
    d = er.diff_paragraphs(old, edited)
    assert d["counts"]["reworded"] == 40 and d["counts"]["added"] == 0 and d["counts"]["removed"] == 0

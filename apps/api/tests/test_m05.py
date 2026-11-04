"""M05: rule types, completed-session handling, quiet hours, cooldown, deliveries, filings, briefings, inbox."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from marketdesk.db import db_session
from marketdesk.models import Alert, AlertDelivery, AlertEvent, Briefing, Instrument
from marketdesk.providers.base import DailyBar
from marketdesk.services import alerts as alerts_svc
from marketdesk.services.alert_rules import crossed, quiet_release, volatility_signal, volume_signal
from marketdesk.services.alerts import (
    evaluate_filings,
    evaluate_session_rule,
    last_bar_complete,
    maintenance,
    run_evaluation_cycle,
)
from marketdesk.services.briefings import due_briefings, generate_briefing

D = Decimal


def cycle(app):
    with db_session() as db:
        return asyncio.run(run_evaluation_cycle(db, app.state.market))


def bars(volumes, closes=None, start=date(2026, 9, 1)):
    closes = closes or [D("100")] * len(volumes)
    return [
        DailyBar(start + timedelta(days=i), None, None, None, D(str(c)), v)
        for i, (v, c) in enumerate(zip(volumes, closes, strict=True))
    ]


# --------------------------------------------------------------------------- pure rules
def test_crossing_needs_two_observations_on_opposite_sides():
    lvl = D("100")
    assert crossed("ABOVE", lvl, None, D("120")) is False  # first observation is only a baseline
    assert crossed("ABOVE", lvl, D("99.99"), D("100")) is True  # reaching the level from below counts
    assert crossed("ABOVE", lvl, D("100"), D("101")) is False  # already at the level: no new crossing
    assert crossed("ABOVE", lvl, D("101"), D("102")) is False  # stays above
    assert crossed("BELOW", lvl, D("100.01"), D("100")) is True
    assert crossed("BELOW", lvl, D("99"), D("98")) is False


def test_volume_and_volatility_use_completed_sessions_and_never_zero_fill():
    window = [1000] * 20
    session, fired, text = volume_signal(bars(window + [2500]), 20, D("2"))
    assert fired and session == date(2026, 9, 21) and "2.50x" in text
    assert volume_signal(bars(window + [1900]), 20, D("2"))[1] is False
    # one missing volume in the window: not evaluated (not treated as zero)
    gappy = bars([*window[:5], None, *window[6:], 9000])
    assert volume_signal(gappy, 20, D("2"))[0] is None
    assert volume_signal(bars([1000] * 10), 20, D("2"))[0] is None  # too few comparable sessions
    flat = bars([1] * 23, [100] * 23)
    assert volatility_signal(flat, 20, D("2"))[0] is None  # zero dispersion cannot be compared
    closes = [100, 101] * 11 + [110]  # alternating ±1% then a +8.9% day
    session, fired, text = volatility_signal(bars([1] * 23, closes), 20, D("3"))
    assert fired and "+8.91%" in text


def test_incomplete_session_is_never_compared_with_full_days():
    # Wednesday 4 Nov 2026, 11:00 New York: the session is open, so a bar dated today is unfinished
    during = datetime(2026, 11, 4, 16, 0, tzinfo=UTC)
    assert last_bar_complete("US", date(2026, 11, 4), during) is False
    assert last_bar_complete("US", date(2026, 11, 3), during) is True
    after = datetime(2026, 11, 4, 21, 30, tzinfo=UTC)  # 16:30 New York, after the close
    assert last_bar_complete("US", date(2026, 11, 4), after) is True
    # India calendar data ends 2026-12-31: unknown status counts as "not complete"
    assert last_bar_complete("IN", date(2027, 1, 4), datetime(2027, 1, 4, 8, 0, tzinfo=UTC)) is False


def test_quiet_hours_overnight_and_across_daylight_saving():
    ist = ZoneInfo("Asia/Kolkata")
    late = datetime(2026, 11, 4, 23, 0, tzinfo=ist)
    assert quiet_release(late, "22:00", "07:00", "Asia/Kolkata") == datetime(2026, 11, 5, 7, 0, tzinfo=ist)
    early = datetime(2026, 11, 5, 6, 0, tzinfo=ist)
    assert quiet_release(early, "22:00", "07:00", "Asia/Kolkata") == datetime(2026, 11, 5, 7, 0, tzinfo=ist)
    assert quiet_release(datetime(2026, 11, 5, 12, 0, tzinfo=ist), "22:00", "07:00", "Asia/Kolkata") is None
    # New York springs forward at 02:00 on 8 Mar 2026: 01:30 EST is 06:30 UTC, 03:00 EDT is 07:00 UTC
    now = datetime(2026, 3, 8, 6, 30, tzinfo=UTC)
    assert quiet_release(now, "01:00", "03:00", "America/New_York") == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
    assert quiet_release(now, "08:00", "08:00", "Asia/Kolkata") is None  # empty window


# --------------------------------------------------------------------------- API validation
@pytest.mark.parametrize(
    "body,field",
    [
        ({"rule": "VOLUME", "target_price": "25"}, "target_price"),
        ({"rule": "VOLATILITY", "target_price": "2", "params": {"lookback": 3}}, "params.lookback"),
        ({"rule": "FILING"}, "rule"),  # fixture listings are not US-registered
        ({"rule": "PRICE", "target_price": "10", "quiet_start": "22:00"}, "quiet_start"),
        ({"rule": "PRICE", "target_price": "10", "quiet_start": "25:00", "quiet_end": "07:00"}, "quiet_start"),
        ({"rule": "PRICE", "target_price": "10", "cooldown_minutes": 1}, "cooldown_minutes"),
        ({"rule": "CROSS"}, "target_price"),
    ],
)
def test_rule_validation(api, body, field):
    r = api.post("/api/alerts", json={"symbol": "SX:AURORA", **body})
    assert r.status_code == 422
    assert field in r.text


# --------------------------------------------------------------------------- observation rules
def test_cross_rule_fires_only_on_an_observed_crossing(api, app):
    price = api.post("/api/alerts", json={"symbol": "SX:AURORA", "rule": "PRICE", "target_price": "160"}).json()
    cross = api.post("/api/alerts", json={"symbol": "SX:AURORA", "rule": "CROSS", "target_price": "172"}).json()
    assert cross["description"] == "Crosses above 172.00"
    assert cycle(app)["triggered"] == 1  # 169.80: PRICE ≥160 fires; CROSS only records a baseline
    api.post("/api/fixture/advance")  # 173.90 crosses 172
    assert cycle(app)["triggered"] == 1
    assert cycle(app)["triggered"] == 0  # same observation again
    evs = {e["alert_id"]: e for e in api.get("/api/alert-events").json()}
    assert set(evs) == {price["id"], cross["id"]}
    assert (
        evs[cross["id"]]["rule"] == "CROSS"
        and "Moved from 169.80 to 173.90, crossing 172.00" in evs[cross["id"]]["explanation"]
    )
    assert evs[cross["id"]]["deliveries"] == [
        {"channel": "in_app", "status": "delivered", "attempts": 1, "last_error": None}
    ]


def test_cooldown_rearms_automatically(api, app):
    aid = api.post("/api/alerts", json={"symbol": "SX:AURORA", "target_price": "160", "cooldown_minutes": 30}).json()[
        "id"
    ]
    assert cycle(app)["triggered"] == 1
    a = api.get("/api/alerts").json()[0]
    assert a["active"] is False and a["rearm_at"] is not None
    with db_session() as db:
        assert maintenance(db, datetime.now(UTC) + timedelta(minutes=10))["rearmed"] == 0
        assert maintenance(db, datetime.now(UTC) + timedelta(minutes=31))["rearmed"] == 1
        alert = db.get(Alert, aid)
        assert alert.active and alert.arm_seq == 2 and alert.rearm_at is None
    api.post("/api/fixture/advance")  # a new observation that still matches fires once for the new arm
    assert cycle(app)["triggered"] == 1
    assert sorted(e["arm_seq"] for e in api.get("/api/alert-events").json()) == [1, 2]


def test_quiet_hours_hold_the_notice_until_the_window_ends(api, app):
    tz = ZoneInfo(api.get("/api/settings").json()["display_timezone"])
    now = datetime.now(tz)
    start, end = (now - timedelta(hours=1)).strftime("%H:%M"), (now + timedelta(hours=1)).strftime("%H:%M")
    api.post(
        "/api/alerts",
        json={"symbol": "SX:AURORA", "target_price": "160", "quiet_start": start, "quiet_end": end},
    )
    assert cycle(app)["triggered"] == 1
    assert api.get("/api/inbox").json() == []  # held: not shown, not counted as unread
    counts = api.get("/api/inbox/counts").json()
    assert counts["alerts"] == 0 and counts["held"] == 1
    assert api.post("/api/inbox/read", json={}).json()["updated"] == 0  # "mark all read" cannot hide held notices
    with db_session() as db:
        ev = db.query(AlertEvent).one()
        assert ev.deliver_after is not None and db.query(AlertDelivery).one().status == "held"
        assert maintenance(db, ev.deliver_after + timedelta(seconds=1))["released"] == 1
        assert db.query(AlertDelivery).one().status == "delivered"
        ev.deliver_after = datetime.now(UTC) - timedelta(seconds=1)  # the window has ended
        db.commit()
    inbox = api.get("/api/inbox").json()
    assert len(inbox) == 1 and inbox[0]["alert"]["deliveries"][0]["status"] == "delivered"


def test_failed_delivery_is_recorded_and_visible(api, app, monkeypatch):
    class Broken:
        def deliver(self, event):
            raise ConnectionError("SMTP refused")

    monkeypatch.setitem(alerts_svc.CHANNELS, "email", Broken())
    api.post("/api/alerts", json={"symbol": "SX:AURORA", "target_price": "160"})
    assert cycle(app)["triggered"] == 1  # one channel failing never loses the event
    ev = api.get("/api/inbox").json()[0]["alert"]
    status = {d["channel"]: (d["status"], d["last_error"]) for d in ev["deliveries"]}
    assert status == {"in_app": ("delivered", None), "email": ("failed", "ConnectionError: SMTP refused")}


# --------------------------------------------------------------------------- session rules
def _volume_alert(api, **params):
    r = api.post(
        "/api/alerts",
        json={"symbol": "SX:AURORA", "rule": "VOLUME", "target_price": "2", "params": {"lookback": 20, **params}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_volume_rule_evaluates_each_completed_session_once(api, app):
    aid = _volume_alert(api)
    now = datetime(2026, 11, 4, 16, 0, tzinfo=UTC)  # New York session open
    series = bars([1000] * 20 + [2500, 99999], start=date(2026, 10, 14))  # last bar = 4 Nov, unfinished
    with db_session() as db:
        alert = db.get(Alert, aid)
        alert.instrument.country = "US"
        db.commit()
        ev = evaluate_session_rule(db, alert, series, "fixture", now)
        assert ev is not None  # judged on 3 Nov (2.5x), not on the unfinished 4 Nov bar
        assert ev.observed_market_time == datetime(2026, 11, 3, tzinfo=UTC) and "2.50x" in ev.explanation
        assert "Completed sessions only" in ev.explanation
        # restart after a crash between writing the event and saving the alert: no duplicate
        alert.active, alert.last_observed_market_time = True, None
        db.commit()
        assert evaluate_session_rule(db, alert, series, "fixture", now) is None
        assert db.query(AlertEvent).count() == 1 and db.get(Alert, aid).active is False


def test_session_rule_records_why_it_was_not_evaluated(api, app):
    aid = _volume_alert(api)
    with db_session() as db:
        alert = db.get(Alert, aid)
        assert evaluate_session_rule(db, alert, bars([1000] * 5), "fixture", datetime.now(UTC)) is None
        assert "Needs 21 completed sessions" in db.get(Alert, aid).last_skip_reason
    api.post("/api/fixture/fault", params={"enabled": True})
    cycle(app)
    assert api.get("/api/alerts").json()[0]["last_skip_reason"].startswith("Not evaluated")
    assert api.get("/api/alert-events").json() == []


# --------------------------------------------------------------------------- filings
def _filing_alert(api) -> int:
    with db_session() as db:
        inst = Instrument(provider="fixture", symbol="SX:USCO", name="Sample US Co", country="US", currency="USD")
        db.add(inst)
        db.flush()
        a = Alert(
            instrument_id=inst.id,
            rule="FILING",
            params={"forms": ["10-K", "8-K"]},
            direction="ABOVE",
            target_price=D("0"),
            active=True,
            arm_seq=1,
            armed_at=datetime(2026, 11, 1, tzinfo=UTC),
        )
        db.add(a)
        db.commit()
        return a.id


def test_filing_rule_creates_one_event_per_new_accession(api, app):
    aid = _filing_alert(api)
    filings = [
        {"form": "8-K", "filing_date": "2026-11-03", "report_date": "2026-11-02", "accession": "0000000001-26-000101",
         "description": "Current report", "document_url": "https://www.sec.gov/Archives/x.htm", "index_url": None},
        {"form": "4", "filing_date": "2026-11-03", "accession": "0000000001-26-000102"},  # form not chosen
        {"form": "10-K", "filing_date": "2026-10-20", "accession": "0000000001-26-000090"},  # before arming
    ]  # fmt: skip
    with db_session() as db:
        alert = db.get(Alert, aid)
        assert len(evaluate_filings(db, alert, filings)) == 1
        assert evaluate_filings(db, alert, filings) == []  # re-checking the same filings never duplicates
        assert db.get(Alert, aid).active is True  # filing rules keep watching
    ev = api.get("/api/alert-events").json()[0]
    assert ev["link"] == "https://www.sec.gov/Archives/x.htm" and "accession 0000000001-26-000101" in ev["explanation"]
    assert ev["observed_price"] is None and ev["target_price"] is None
    # without SEC configuration the rule is skipped with a reason, not silently passed
    cycle(app)
    with db_session() as db:
        assert "SEC data is not configured" in db.get(Alert, aid).last_skip_reason


# --------------------------------------------------------------------------- briefings + inbox
def test_briefings_follow_exchange_calendars():
    # 08:00 IST Wed 4 Nov 2026 = 02:30 UTC = 21:30 Tue in New York
    due = {(k, m, d) for k, m, d, _ in due_briefings(datetime(2026, 11, 4, 2, 30, tzinfo=UTC))}
    assert due == {("morning", "IN", date(2026, 11, 4)), ("close", "IN", date(2026, 11, 3)),
                   ("close", "US", date(2026, 11, 3))}  # fmt: skip
    # Saturday: no morning briefing anywhere; the close briefings are still Friday's
    sat = {(k, m, d) for k, m, d, _ in due_briefings(datetime(2026, 11, 7, 6, 0, tzinfo=UTC))}
    assert sat == {("close", "IN", date(2026, 11, 6)), ("close", "US", date(2026, 11, 6))}
    # Beyond the India calendar's published data: nothing for India, never a guess
    assert {m for _, m, _, _ in due_briefings(datetime(2027, 1, 5, 4, 0, tzinfo=UTC))} == {"US"}


def test_briefing_is_stored_once_and_appears_in_the_inbox(api, app):
    wid = api.post("/api/watchlists", json={"name": "Core"}).json()["id"]
    for sym in ("SX:AURORA", "SX:BANYAN"):
        api.post(f"/api/watchlists/{wid}/items", json={"symbol": sym})
    api.post("/api/alerts", json={"symbol": "SX:AURORA", "target_price": "160"})
    cycle(app)  # one alert event
    session = asyncio.run(app.state.market.history("SX:AURORA", "3M")).value.bars[-1].session_date
    with db_session() as db:
        first = asyncio.run(generate_briefing(db, app.state.market, "close", "IN", session, {}))
        assert first is not None
        assert asyncio.run(generate_briefing(db, app.state.market, "close", "IN", session, {})) is None
        assert db.query(Briefing).count() == 1
        assert asyncio.run(generate_briefing(db, app.state.market, "close", "US", session, {})) is None  # no symbols
    inbox = api.get("/api/inbox").json()
    assert [i["type"] for i in inbox] == ["briefing", "alert"]
    b = inbox[0]["briefing"]
    assert b["kind"] == "close" and b["market"] == "IN" and b["data_status"] == "sample"
    moves = [i for i in b["items"] if i["kind"] == "move"]
    assert {m["symbol"] for m in moves} == {"SX:AURORA", "SX:BANYAN"}
    assert all(f"{session.day} {session:%b %Y}" in m["text"] for m in moves)
    assert any(i["kind"] == "alert" for i in b["items"])
    assert not any(w in str(b).lower() for w in ("because", "buy", "sell"))
    # filters, read state, counts
    assert [i["type"] for i in api.get("/api/inbox", params={"type": "alert"}).json()] == ["alert"]
    assert api.get("/api/inbox", params={"market": "US"}).json() == []
    assert api.get("/api/inbox/counts").json() == {"alerts": 1, "briefings": 1, "total": 2, "held": 0}
    assert api.post("/api/inbox/read", json={"type": "briefing", "id": b["id"]}).json()["updated"] == 1
    assert [i["type"] for i in api.get("/api/inbox", params={"unread": True}).json()] == ["alert"]
    assert api.post("/api/inbox/read", json={"type": "briefing", "id": 999}).status_code == 404
    assert api.post("/api/inbox/read", json={}).json()["updated"] == 1
    assert api.get("/api/inbox/counts").json()["total"] == 0


def test_close_briefing_waits_for_the_sessions_bars(api, app):
    wid = api.post("/api/watchlists", json={"name": "Core"}).json()["id"]
    api.post(f"/api/watchlists/{wid}/items", json={"symbol": "SX:AURORA"})
    later = date(2026, 12, 1)  # no fixture bar for this date
    closes = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
    with db_session() as db:
        info = {"closes_at": closes}
        early = asyncio.run(generate_briefing(db, app.state.market, "close", "IN", later, info, closes))
        assert early is None  # within the grace period: retry later rather than publish an empty close
        late = asyncio.run(
            generate_briefing(db, app.state.market, "close", "IN", later, info, closes + timedelta(hours=7))
        )
        assert late is not None
        cov = [i for i in late.content["items"] if i["kind"] == "coverage"]
        assert cov and "no completed bar for 1 Dec 2026" in cov[0]["text"]


def test_inbox_rejects_bad_filters(api):
    assert api.get("/api/inbox", params={"market": "UK"}).status_code == 422
    assert api.post("/api/inbox/read", json={"id": 3}).status_code == 422


def test_due_briefing_sessions_are_real(api):
    # The helper used by the worker exposes calendar times, not weekday guesses
    _, _, day, info = next(x for x in due_briefings(datetime(2026, 11, 4, 2, 30, tzinfo=UTC)) if x[0] == "morning")
    assert info["opens_at"] == datetime(2026, 11, 4, 3, 45, tzinfo=UTC)  # 09:15 IST
    assert info["previous_session"] == date(2026, 11, 3)
    assert SimpleNamespace(**info).closes_at == datetime(2026, 11, 4, 10, 0, tzinfo=UTC)  # 15:30 IST


def test_fixture_briefing_path_and_no_calendar_briefings_from_samples(api, app):
    assert api.post("/api/fixture/briefing").status_code == 409  # nothing watchlisted yet
    wid = api.post("/api/watchlists", json={"name": "Core"}).json()["id"]
    api.post(f"/api/watchlists/{wid}/items", json={"symbol": "SX:AURORA"})
    r = api.post("/api/fixture/briefing")
    assert r.status_code == 201 and r.json()["session_date"] == "2026-06-30" and r.json()["data_status"] == "sample"
    assert api.post("/api/fixture/briefing").status_code == 409  # once per session
    from marketdesk.services.briefings import run_due_briefings

    with db_session() as db:
        assert asyncio.run(run_due_briefings(db, app.state.market))["generated"] == []


# --------------------------------------------------------------------------- data migration
_M05_COLUMNS = {
    "alerts": {"rule", "params", "cooldown_minutes", "rearm_at", "quiet_start", "quiet_end", "last_skip_reason"},
    "alert_events": {"rule", "explanation", "link", "deliver_after"},
}


def _as_0003(data: dict) -> dict:
    """Rewrite a current backup as the previous version (schema 0003) would have produced it."""
    from marketdesk.services.backup import checksum

    old = json.loads(json.dumps(data))
    old["schema_revision"] = "0003"
    for table in ("alert_deliveries", "briefings"):
        old["tables"].pop(table, None)
    for name, drop in _M05_COLUMNS.items():
        tab = old["tables"][name]
        keep = [i for i, c in enumerate(tab["columns"]) if c not in drop]
        tab["columns"] = [tab["columns"][i] for i in keep]
        tab["rows"] = [[row[i] for i in keep] for row in tab["rows"]]
    old["counts"] = {k: len(v["rows"]) for k, v in old["tables"].items()}
    old["checksum"] = checksum(old["tables"])
    return old


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_pre_m05_backup_with_alerts_restores_and_migrates(tmp_path, backend):
    """Regression: restoring an older backup must not insert columns that only exist in later schema revisions."""
    from fastapi.testclient import TestClient

    from marketdesk.api.app import create_app
    from marketdesk.cli import restore_with_migrations
    from marketdesk.db import get_engine
    from tests.conftest import PG_URL, Api, _reset_postgres, make_settings, migrated

    if backend == "postgresql" and not PG_URL:
        pytest.skip("needs TEST_DATABASE_URL (PostgreSQL)")
    src = migrated(make_settings(tmp_path / "src", marketdesk_env="development", dev_auth_bypass=True))
    app = create_app(src)
    with TestClient(app) as c:
        api = Api(c)
        api.refresh_csrf()
        api.post("/api/alerts", json={"symbol": "SX:AURORA", "direction": "ABOVE", "target_price": "160", "note": "x"})
        api.post("/api/alerts", json={"symbol": "SX:BANYAN", "direction": "BELOW", "target_price": "1"})
        with db_session() as db:
            assert asyncio.run(run_evaluation_cycle(db, app.state.market))["triggered"] == 1
        data = api.get("/api/backup/export").json()
    old = _as_0003(data)
    if backend == "postgresql":
        _reset_postgres(PG_URL)
        url = PG_URL
    else:
        url = f"sqlite:///{tmp_path}/restored.db"
    dst = make_settings(tmp_path / "dst", marketdesk_env="development", dev_auth_bypass=True, database_url=url)
    app = create_app(dst)
    counts = restore_with_migrations(dst.effective_database_url, get_engine(), old)
    assert counts["alerts"] == 2 and counts["alert_events"] == 1
    with TestClient(app) as c:
        api = Api(c)
        alerts = sorted(api.get("/api/alerts").json(), key=lambda a: a["id"])
        assert [(a["rule"], a["target_price"], a["cooldown_minutes"], a["note"]) for a in alerts] == [
            ("PRICE", "160", None, "x"),
            ("PRICE", "1", None, None),
        ]
        ev = api.get("/api/inbox").json()
        assert [(i["type"], i["alert"]["rule"], i["alert"]["deliveries"]) for i in ev] == [("alert", "PRICE", [])]

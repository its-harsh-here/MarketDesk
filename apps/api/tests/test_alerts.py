"""Alert evaluation: fires once, rearm, restart idempotency, stale data is never evaluated."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from marketdesk.db import db_session
from marketdesk.models import Alert, AlertEvent, QuoteObservation
from marketdesk.services.alerts import evaluate_alert, record_observation, run_evaluation_cycle


def cycle(app):
    with db_session() as db:
        return asyncio.run(run_evaluation_cycle(db, app.state.market))


def make_alert(api, target="172.00", direction="ABOVE", symbol="SX:AURORA"):
    r = api.post("/api/alerts", json={"symbol": symbol, "direction": direction, "target_price": target})
    assert r.status_code == 201
    return r.json()["id"]


def events(api):
    return api.get("/api/alert-events").json()


def test_alert_fires_once_and_can_be_rearmed(api, app):
    aid = make_alert(api)
    assert cycle(app)["triggered"] == 0  # 169.80 at base date
    assert cycle(app)["evaluated"] == 0  # same observation is not re-evaluated
    api.post("/api/fixture/advance")  # 173.90
    assert cycle(app)["triggered"] == 1
    assert cycle(app)["triggered"] == 0
    assert len(events(api)) == 1
    alert = api.get("/api/alerts").json()[0]
    assert alert["active"] is False and alert["last_observed_price"] == "173.9"
    # rearm: the already-seen observation does not fire again; the next matching one does
    assert api.post(f"/api/alerts/{aid}/rearm").json()["arm_seq"] == 2
    assert api.post(f"/api/alerts/{aid}/rearm").status_code == 409
    assert cycle(app)["triggered"] == 0
    api.post("/api/fixture/advance")  # 175.80
    assert cycle(app)["triggered"] == 1
    evs = events(api)
    assert len(evs) == 2 and {e["arm_seq"] for e in evs} == {1, 2}
    # notifications can be marked read
    assert len(api.get("/api/alert-events", params={"unread": True}).json()) == 2
    api.post("/api/alert-events/read")
    assert api.get("/api/alert-events", params={"unread": True}).json() == []


def test_worker_restart_does_not_duplicate_events(api, app):
    aid = make_alert(api, target="170")
    api.post("/api/fixture/advance")
    with db_session() as db:
        alert = db.get(Alert, aid)
        q = asyncio.run(app.state.market.quote("SX:AURORA")).value
        obs = record_observation(db, alert.instrument, "fixture", q, datetime.now(UTC))
        assert evaluate_alert(db, alert, obs, "fixture") is not None
        # Simulate a crash after the event was written but before the alert state was persisted
        alert.active = True
        alert.last_observation_id = None
        db.commit()
        # Re-recording the same quote returns the same observation (idempotent by market time)
        again = record_observation(db, alert.instrument, "fixture", q, datetime.now(UTC))
        assert again.id == obs.id
        assert evaluate_alert(db, alert, again, "fixture") is None
        assert db.query(AlertEvent).count() == 1
        assert db.query(QuoteObservation).count() == 1
        assert db.get(Alert, aid).active is False


def test_stale_or_failed_quotes_are_not_evaluated(api, app):
    make_alert(api, target="100", direction="ABOVE")  # would match immediately
    api.post("/api/fixture/fault", params={"enabled": True})
    summary = cycle(app)
    assert summary["triggered"] == 0 and summary["skipped"][0]["status"] in ("stale", "unavailable")
    assert events(api) == []
    api.post("/api/fixture/fault", params={"enabled": False})
    assert cycle(app)["triggered"] == 1


def test_observation_from_other_provider_is_ignored(api, app):
    aid = make_alert(api, target="1")
    with db_session() as db:
        alert = db.get(Alert, aid)
        obs = QuoteObservation(
            instrument_id=alert.instrument_id,
            provider="yahoo",
            price=alert.target_price * 10,
            market_time=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
        )
        db.add(obs)
        db.commit()
        assert evaluate_alert(db, alert, obs, "fixture") is None


def test_alert_validation(api):
    r = api.post("/api/alerts", json={"symbol": "SX:AURORA", "direction": "ABOVE", "target_price": "-1"})
    assert r.status_code == 422
    r = api.post("/api/alerts", json={"symbol": "SX:AURORA", "direction": "ABOVE", "target_price": "1.00001"})
    assert r.status_code == 422
    r = api.post("/api/alerts", json={"symbol": "NOPE.NS", "direction": "ABOVE", "target_price": "1"})
    assert r.status_code == 422

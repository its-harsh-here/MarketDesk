"""M10: structured theses, immutable versions with evidence, explicit edits, reviews, comparison, migration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, text

from marketdesk.db.migrations import upgrade
from marketdesk.providers.base import CorporateAction
from marketdesk.services.clock import today_local

BASE = {
    "symbol": "SX:AURORA",
    "entry_date": "2026-06-30",
    "title": "Grid buildout",
    "thesis": "Capacity additions lift earnings.",
    "risks": "Tariff review.",
    "invalidation": "Two quarters of falling utilisation.",
    "decision": "BUY",
    "conviction": 3,
    "horizon": "2-3 years",
    "tags": ["power"],
}


def create(api, **over):
    r = api.post("/api/journal", json={**BASE, **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_stores_version_one_with_evidence(api):
    e = create(api)
    assert (e["decision"], e["conviction"], e["horizon"], e["version"]) == ("BUY", 3, "2-3 years", 1)
    d = api.get(f"/api/journal/{e['id']}").json()
    (v1,) = d["versions"]
    assert v1["version"] == 1 and v1["change_note"] is None
    assert v1["content"]["thesis"] == "Capacity additions lift earnings." and v1["content"]["decision"] == "BUY"
    ev = v1["evidence"]
    assert ev["captured"] is True and ev["symbol"] == "SX:AURORA"
    assert ev["price"] == {
        "value": "169.8",
        "currency": "INR",
        "market_time": ev["price"]["market_time"],
        "session_date": "2026-06-30",
        "status": "sample",
    }
    assert ev["fundamentals"]["status"] in ("sample", "available")
    assert ev["filings"]["status"] == "not_applicable"  # not a US registrant


def test_edits_are_explicit_and_versions_immutable(api):
    e = create(api)
    eid = e["id"]
    # organising metadata changes in place, without a new version
    r = api.put(f"/api/journal/{eid}", json={**BASE, "tags": ["power", "core"], "review_date": "2026-09-30"})
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["tags"] == ["core", "power"]
    # a thesis change without saying why is refused
    changed = {**BASE, "thesis": "Capacity additions lift earnings; tariffs now settled.", "conviction": 4}
    r = api.put(f"/api/journal/{eid}", json=changed)
    assert r.status_code == 422 and r.json()["error"]["details"]["fields"][0]["field"] == "change_note"
    api.post("/api/fixture/advance")  # the market moves before the edit
    r = api.put(f"/api/journal/{eid}", json={**changed, "change_note": "Tariff review concluded in our favour."})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["conviction"] == 4
    d = api.get(f"/api/journal/{eid}").json()
    v1, v2 = d["versions"]
    assert v1["content"]["thesis"] == BASE["thesis"] and v1["content"]["conviction"] == 3  # original kept as written
    assert v1["evidence"]["price"]["value"] == "169.8"  # today's data never replaces the original snapshot
    assert v2["change_note"] == "Tariff review concluded in our favour." and v2["evidence"]["price"]["value"] == "173.9"
    # the instrument a note is about cannot change
    r = api.put(f"/api/journal/{eid}", json={**changed, "symbol": "SX:BANYAN", "change_note": "x"})
    assert r.status_code == 422 and "instrument cannot change" in r.json()["error"]["message"]
    assert len(api.get(f"/api/journal/{eid}").json()["versions"]) == 2


def test_compare_shows_then_and_now_without_storing_now(api, app, monkeypatch):
    e = create(api)
    api.post("/api/fixture/advance")  # 169.80 -> 173.90
    c = api.get(f"/api/journal/{e['id']}/compare", params={"version": 1}).json()
    assert c["then"]["price"]["value"] == "169.8" and c["now"]["price"]["value"] == "173.9"
    assert Decimal(c["price_change_pct"]).quantize(Decimal("0.01")) == Decimal("2.41")
    assert "dividends are not included" in c["price_note"] and c["splits_since"] == []
    assert api.get(f"/api/journal/{e['id']}").json()["versions"][0]["evidence"]["price"]["value"] == "169.8"
    # a split after the snapshot makes a raw price comparison meaningless: it is withheld and explained
    market = app.state.market
    original = market.actions

    async def with_split(symbol):
        r = await original(symbol)
        tomorrow = datetime.now(UTC).date() + timedelta(days=1)
        r.value.append(CorporateAction(tomorrow, "SPLIT", Decimal(2), "2-for-1 split (test)"))
        return r

    monkeypatch.setattr(market, "actions", with_split)
    c = api.get(f"/api/journal/{e['id']}/compare").json()
    assert c["price_change_pct"] is None and "split happened" in c["price_note"] and len(c["splits_since"]) == 1
    assert api.get(f"/api/journal/{e['id']}/compare", params={"version": 9}).status_code == 404


def test_review_queue_and_history(api, app):
    from marketdesk.db import db_session

    with db_session() as db:
        today = today_local(db)
    e = create(api, entry_date=(today - timedelta(days=30)).isoformat(), review_date=today.isoformat())
    later = create(api, title="Later", review_date=(today + timedelta(days=30)).isoformat())
    due = api.get("/api/journal", params={"due": True}).json()
    assert [x["id"] for x in due["items"]] == [e["id"]] and due["items"][0]["review_due"] is True
    bad = api.post(f"/api/journal/{e['id']}/reviews", json={"outcome": "intact", "next_review_date": today.isoformat()})
    assert bad.status_code == 422
    assert api.post(f"/api/journal/{e['id']}/reviews", json={"outcome": "maybe"}).status_code == 422
    nxt = (today + timedelta(days=90)).isoformat()
    body = {"outcome": "weakened", "notes": "Utilisation dipped.", "next_review_date": nxt}
    r = api.post(f"/api/journal/{e['id']}/reviews", json=body)
    assert r.status_code == 201
    rv = r.json()
    assert rv["outcome"] == "weakened" and rv["version"] == 1 and rv["scheduled_for"] == today.isoformat()
    assert rv["evidence"]["price"]["value"] is not None
    assert api.get("/api/journal", params={"due": True}).json()["items"] == []  # the queue moved on
    d = api.get(f"/api/journal/{e['id']}").json()
    assert d["review_date"] == nxt and [x["outcome"] for x in d["reviews"]] == ["weakened"]
    # closing with no next review leaves the entry out of the queue for good
    api.post(f"/api/journal/{e['id']}/reviews", json={"outcome": "closed"})
    d = api.get(f"/api/journal/{e['id']}").json()
    assert d["review_date"] is None and [x["outcome"] for x in d["reviews"]] == ["closed", "weakened"]
    assert api.get(f"/api/journal/{later['id']}").json()["reviews"] == []
    # deleting the whole note (an explicit, confirmed action) removes its history with it
    assert api.delete(f"/api/journal/{e['id']}").status_code == 204
    assert api.get(f"/api/journal/{e['id']}").status_code == 404


def test_validation(api):
    assert api.post("/api/journal", json={**BASE, "conviction": 7}).status_code == 422
    assert api.post("/api/journal", json={**BASE, "decision": "YOLO"}).status_code == 422
    e = create(api, decision=None, conviction=None, horizon=None)
    assert (e["decision"], e["conviction"], e["horizon"]) == (None, None, None)


def test_migration_0006_backfills_version_one_and_keeps_entries(tmp_path):
    url = f"sqlite:///{tmp_path}/j.db"
    upgrade(url, "0005")
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO instruments (provider, symbol, name, created_at, updated_at) "
                "VALUES ('fixture', 'SX:AURORA', 'Aurora', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        c.execute(
            text(
                "INSERT INTO journal_entries (instrument_id, entry_date, title, thesis, risks, invalidation, "
                "review_date, created_at, updated_at) VALUES (1, '2026-02-01', 'Old note', 'Old thesis', "
                "'Old risk', 'Old exit', '2026-03-01', '2026-02-01 09:00:00', '2026-02-01 09:00:00')"
            )
        )
        before = c.execute(text("SELECT id, entry_date, title, thesis, risks, invalidation FROM journal_entries")).all()
    upgrade(url, "head")
    with eng.connect() as c:
        after = c.execute(text("SELECT id, entry_date, title, thesis, risks, invalidation FROM journal_entries")).all()
        assert after == before
        assert c.execute(text("SELECT version FROM journal_entries")).scalar() == 1
        row = c.execute(text("SELECT version, change_note, content, evidence FROM journal_versions")).one()
    import json

    content, evidence = json.loads(row[2]), json.loads(row[3])
    assert row[0] == 1 and "before versioning" in row[1]
    assert content["thesis"] == "Old thesis" and content["entry_date"] == "2026-02-01" and content["decision"] is None
    assert evidence["captured"] is False and "no evidence was captured" in evidence["reason"]
    assert date.fromisoformat(content["entry_date"]) == date(2026, 2, 1)

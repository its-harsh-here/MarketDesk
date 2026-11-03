"""M00 operational foundation: request IDs and safe server errors, sign-in outcomes, configuration diagnostics,
worker settings, session expiry/cookies, schema status, and logical backup/restore across databases."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

from marketdesk.api.app import create_app
from marketdesk.config import ConfigError, Settings, password_hash_problem, validate_settings
from marketdesk.db import db_session, get_engine
from marketdesk.services import auth
from marketdesk.services.alerts import run_evaluation_cycle
from marketdesk.services.backup import BackupError, export_data, import_data

from .conftest import OWNER_HASH, OWNER_PW, PG_URL, Api, _reset_postgres, make_settings, migrated


def _login(api, username="owner"):
    r = api.post("/api/auth/login", json={"username": username, "password": OWNER_PW})
    assert r.status_code == 200, r.text
    api.csrf = r.json()["csrf_token"]


# --------------------------------------------------------------------------- request IDs and server errors
def test_every_response_has_a_request_id_and_errors_repeat_it(owner_api):
    api, _ = owner_api
    r = api.get("/api/health")
    assert len(r.headers["x-request-id"]) == 16
    r = api.get("/api/watchlists", headers={"X-Request-ID": "proxy-abc-123"})
    assert r.status_code == 401
    assert r.headers["x-request-id"] == "proxy-abc-123"  # a well-formed upstream ID is kept
    assert r.json()["error"]["request_id"] == "proxy-abc-123"
    r = api.get("/api/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.headers["x-request-id"] != "bad id\nwith newline" and len(r.headers["x-request-id"]) == 16


def test_unhandled_failure_returns_a_safe_500_with_reference_and_logs_it(tmp_path, caplog):
    s = migrated(make_settings(tmp_path))
    app = create_app(s)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret-looking detail that must not reach the client")

    with TestClient(app, raise_server_exceptions=False) as c, caplog.at_level(logging.ERROR, "marketdesk"):
        r = c.get("/boom")
    body = r.json()["error"]
    assert r.status_code == 500 and body["code"] == "internal_error"
    assert body["request_id"] == r.headers["x-request-id"]
    assert body["request_id"] in body["message"]  # shown to the owner as a reference
    assert "secret-looking" not in r.text
    logged = [rec for rec in caplog.records if body["request_id"] in rec.getMessage()]
    assert logged and "RuntimeError" in logged[0].getMessage()


# --------------------------------------------------------------------------- sign-in outcomes
def test_sign_in_outcomes(owner_api):
    api, _ = owner_api
    r = api.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    assert api.post("/api/auth/login", json={"username": "owner"}).status_code == 422
    _login(api, username="owner ")  # a trailing space from a mobile keyboard is not a different user
    assert api.get("/api/watchlists").status_code == 200


def test_rate_limit_reports_retry_time(owner_api):
    api, s = owner_api
    for i in range(s.login_max_failures):
        api.post("/api/auth/login", json={"username": "owner", "password": f"wrong-{i}"})
    r = api.post("/api/auth/login", json={"username": "owner", "password": OWNER_PW})
    assert r.status_code == 429
    assert r.json()["error"]["details"]["retry_after_seconds"] == int(r.headers["retry-after"]) > 0


def test_expired_session_is_rejected(owner_api, monkeypatch):
    api, s = owner_api
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() - (s.session_ttl_hours * 3600 + 60))
    token, _ = auth.issue_session(s, "owner")  # issued long enough ago to have expired
    monkeypatch.setattr(time, "time", real)
    api.c.cookies.set("md_session", token)
    assert api.get("/api/watchlists").status_code == 401
    assert api.get("/api/auth/session").json()["authenticated"] is False


def test_production_cookie_is_secure_httponly_lax(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="production", data_provider="yahoo"))
    with TestClient(create_app(s), base_url="https://desk.example") as c:
        r = c.post("/api/auth/login", json={"username": "owner", "password": OWNER_PW})
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 200
    for attr in ("httponly", "secure", "samesite=lax", "path=/"):
        assert attr in cookie


# --------------------------------------------------------------------------- configuration
def test_password_hash_diagnostics_name_the_actual_problem():
    assert password_hash_problem(OWNER_HASH) is None
    assert "quotes" in password_hash_problem(f"'{OWNER_HASH}'")
    assert "$$" in password_hash_problem(OWNER_HASH.replace("$", "$$"))
    assert "cut off" in password_hash_problem(OWNER_HASH[:-10])
    assert "argon2" in password_hash_problem("$2b$12$abcdefghijklmnopqrstuv")
    assert "MiB" in password_hash_problem(OWNER_HASH.replace("m=65536", "m=4194304"))


def test_pasted_whitespace_is_ignored_and_bad_hash_refused_at_startup(tmp_path):
    s = Settings(
        marketdesk_env="production",
        data_dir=tmp_path,
        owner_username=" owner\n",
        owner_password_hash=OWNER_HASH + "\n",
        session_secret="x" * 40,
    )
    assert s.owner_username == "owner" and s.owner_password_hash == OWNER_HASH
    validate_settings(s)
    bad = s.model_copy(update={"owner_password_hash": f'"{OWNER_HASH}"'})
    with pytest.raises(ConfigError, match="quotes"):
        validate_settings(bad)


def test_worker_does_not_need_web_credentials(tmp_path):
    s = Settings(marketdesk_env="production", data_dir=tmp_path)  # no owner login, no session secret
    with pytest.raises(ConfigError):
        validate_settings(s)
    validate_settings(s, role="worker")


def test_status_reports_schema_state(api):
    schema = api.get("/api/status").json()["schema"]
    assert schema["up_to_date"] is True and schema["current"] == schema["head"]


# --------------------------------------------------------------------------- logical backup / restore
def _populate(api, app):
    api.patch("/api/settings", json={"theme": "light", "display_timezone": "America/New_York"})
    wid = api.post("/api/watchlists", json={"name": "Keep"}).json()["id"]
    for sym in ("SX:AURORA", "SX:BANYAN"):
        api.post(f"/api/watchlists/{wid}/items", json={"symbol": sym})
    for t in (
        {"type": "DEPOSIT", "effective_date": "2026-01-02", "amount": "10000"},
        {
            "type": "BUY",
            "effective_date": "2026-01-03",
            "symbol": "SX:AURORA",
            "quantity": "10",
            "price": "100.1234",
            "fees": "10.05",
        },
        {
            "type": "SELL",
            "effective_date": "2026-01-05",
            "symbol": "SX:AURORA",
            "quantity": "2.5",
            "price": "130",
            "fees": "5",
        },
    ):
        assert api.post("/api/portfolio/transactions", json=t).status_code == 201
    api.post("/api/alerts", json={"symbol": "SX:AURORA", "direction": "ABOVE", "target_price": "172"})
    api.post("/api/fixture/advance")
    with db_session() as db:
        assert asyncio.run(run_evaluation_cycle(db, app.state.market))["triggered"] == 1
    api.post(
        "/api/journal", json={"symbol": "SX:AURORA", "entry_date": "2026-01-02", "title": "Thesis", "tags": ["core"]}
    )


def _snapshot(api):
    summary = api.get("/api/portfolio/summary").json()
    return {
        "watchlists": [(w["name"], [i["symbol"] for i in w["items"]]) for w in api.get("/api/watchlists").json()],
        "transactions": api.get("/api/portfolio/transactions").json()["total"],
        "cash": summary["cash"],
        "holdings": [(h["symbol"], h["quantity"], h["cost_basis"]) for h in summary["holdings"]],
        "realized": summary["realized_pnl"],
        "alerts": [(a["direction"], a["target_price"], a["active"]) for a in api.get("/api/alerts").json()],
        "events": len(api.get("/api/alert-events").json()),
        "journal": [(e["title"], e["tags"]) for e in api.get("/api/journal").json()["items"]],
        "prefs": {k: v for k, v in api.get("/api/settings").json().items() if k in ("theme", "display_timezone")},
    }


def _source(tmp_path):
    s = migrated(make_settings(tmp_path / "src", marketdesk_env="development", dev_auth_bypass=True))
    app = create_app(s)
    with TestClient(app) as c:
        api = Api(c)
        api.refresh_csrf()
        _populate(api, app)
        before = _snapshot(api)
        r = api.get("/api/backup/export")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        assert "attachment" in r.headers["content-disposition"]
    return r.json(), before


def _restore_and_compare(target_settings, data, before):
    from marketdesk.db.migrations import current_revision

    s = migrated(target_settings)
    app = create_app(s)
    rev = current_revision(s.effective_database_url)
    counts = import_data(get_engine(), data, rev)
    assert counts == data["counts"]
    with TestClient(app) as c:
        api = Api(c)
        api.refresh_csrf()
        assert _snapshot(api) == before
        again = export_data(get_engine(), rev)
        assert again["checksum"] == data["checksum"]  # identical data after the round trip
        # ids continue after the restored rows (sequences reset on PostgreSQL)
        assert api.post("/api/watchlists", json={"name": "After restore"}).status_code == 201
        with pytest.raises(BackupError, match="already contains data"):
            import_data(get_engine(), data, rev)


def test_backup_round_trip_into_empty_sqlite(tmp_path):
    data, before = _source(tmp_path)
    assert data["counts"]["ledger_transactions"] == 3 and data["counts"]["alert_events"] == 1
    target = make_settings(
        tmp_path / "dst",
        marketdesk_env="development",
        dev_auth_bypass=True,
        database_url=f"sqlite:///{tmp_path}/dst.db",
    )
    _restore_and_compare(target, data, before)


@pytest.mark.skipif(not PG_URL, reason="needs TEST_DATABASE_URL (PostgreSQL)")
def test_backup_round_trip_sqlite_to_postgres(tmp_path):
    data, before = _source(tmp_path / "s")  # with PG_URL set the source is PostgreSQL too
    _reset_postgres(PG_URL)
    target = make_settings(tmp_path / "pg", marketdesk_env="development", dev_auth_bypass=True, database_url=PG_URL)
    _restore_and_compare(target, data, before)


def test_backup_refuses_tampered_or_mismatched_files(tmp_path):
    data, _ = _source(tmp_path)
    s = migrated(make_settings(tmp_path / "t", database_url=f"sqlite:///{tmp_path}/t.db"))
    create_app(s)
    from marketdesk.db.migrations import current_revision

    rev = current_revision(s.effective_database_url)
    tampered = json.loads(json.dumps(data))
    tampered["tables"]["ledger_transactions"]["rows"][0][0] = 999
    with pytest.raises(BackupError, match="checksum"):
        import_data(get_engine(), tampered, rev)
    with pytest.raises(BackupError, match="schema revision"):
        import_data(get_engine(), data, "0000_other")
    with pytest.raises(BackupError, match="not a MarketDesk backup"):
        import_data(get_engine(), {"hello": "world"}, rev)


def test_backup_download_requires_sign_in(owner_api):
    api, _ = owner_api
    assert api.get("/api/backup/export").status_code == 401

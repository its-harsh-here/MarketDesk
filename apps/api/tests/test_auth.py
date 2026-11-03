"""Authentication, CSRF, configuration safety and the read-only public demo."""

from __future__ import annotations

import pytest

from marketdesk.config import ConfigError, validate_settings

from .conftest import OWNER_PW, Api, make_settings


def test_private_api_requires_login(owner_api):
    api, _ = owner_api
    for url in (
        "/api/watchlists",
        "/api/portfolio/summary",
        "/api/alerts",
        "/api/journal",
        "/api/status",
        "/api/market/snapshots?symbols=SX:AURORA",
        "/api/portfolio/export/transactions.csv",
    ):
        r = api.get(url)
        assert r.status_code == 401, url
        assert r.json()["error"]["code"] == "unauthorized"
    assert api.post("/api/watchlists", json={"name": "x"}).status_code == 401
    # health remains public and non-sensitive
    assert api.get("/api/health").json() == {"status": "ok"}


def test_login_session_csrf_and_logout(owner_api):
    api, settings = owner_api
    assert api.post("/api/auth/login", json={"username": "owner", "password": "wrong"}).status_code == 401
    r = api.post("/api/auth/login", json={"username": "owner", "password": OWNER_PW})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    api.csrf = r.json()["csrf_token"]
    assert api.get("/api/watchlists").status_code == 200
    # mutation without CSRF token is rejected
    assert api.c.post("/api/watchlists", json={"name": "x"}).status_code == 403
    # foreign origin is rejected even with the token
    bad = api.post("/api/watchlists", json={"name": "x"}, headers={"origin": "https://evil.example"})
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "bad_origin"
    assert api.post("/api/watchlists", json={"name": "x"}, headers={"origin": "http://testserver"}).status_code == 201
    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/watchlists").status_code == 401


def test_login_rate_limit(owner_api):
    api, settings = owner_api
    for _ in range(settings.login_max_failures):
        assert api.post("/api/auth/login", json={"username": "owner", "password": "nope"}).status_code == 401
    r = api.post("/api/auth/login", json={"username": "owner", "password": OWNER_PW})
    assert r.status_code == 429 and "retry-after" in r.headers


def test_wrong_username_is_rejected(owner_api):
    api, _ = owner_api
    assert api.post("/api/auth/login", json={"username": "admin", "password": OWNER_PW}).status_code == 401


def test_production_requires_credentials_and_secret(tmp_path):
    with pytest.raises(ConfigError, match="SESSION_SECRET"):
        validate_settings(make_settings(tmp_path, marketdesk_env="production", session_secret=None))
    with pytest.raises(ConfigError, match="OWNER_PASSWORD_HASH"):
        validate_settings(make_settings(tmp_path, marketdesk_env="production", owner_password_hash="plaintext"))
    with pytest.raises(ConfigError, match="OWNER_USERNAME"):
        validate_settings(make_settings(tmp_path, marketdesk_env="production", owner_username=None))
    validate_settings(make_settings(tmp_path, marketdesk_env="production", data_provider="yahoo"))


def test_dev_bypass_rejected_outside_development(tmp_path):
    for env in ("production", "test"):
        with pytest.raises(ConfigError, match="DEV_AUTH_BYPASS"):
            validate_settings(make_settings(tmp_path, marketdesk_env=env, dev_auth_bypass=True))


def test_production_refuses_synthetic_fixture_data(tmp_path):
    """Real data only in production: the fixture provider is a test harness."""
    with pytest.raises(ConfigError, match="DATA_PROVIDER=fixture"):
        validate_settings(make_settings(tmp_path, marketdesk_env="production", data_provider="fixture"))
    # development/test may use it for deterministic tests
    validate_settings(make_settings(tmp_path, marketdesk_env="test", data_provider="fixture"))


def test_default_provider_is_real_market_data(monkeypatch):
    from marketdesk.config import Settings

    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    assert Settings().data_provider == "yahoo"


def test_public_demo_mode_no_longer_exists(owner_api):
    api, _ = owner_api
    # the removed synthetic showcase endpoints are gone
    assert api.post("/api/workspace/sample-portfolio").status_code in (401, 404)


def _login(api) -> str:
    r = api.post("/api/auth/login", json={"username": "owner", "password": OWNER_PW})
    assert r.status_code == 200
    api.csrf = r.json()["csrf_token"]
    return api.c.cookies.get("md_session")


def test_signin_survives_restart_and_database_reset(tmp_path):
    from fastapi.testclient import TestClient

    from marketdesk.api.app import create_app

    s = make_settings(tmp_path / "a")
    with TestClient(create_app(s)) as c:
        token = _login(Api(c))
    # a brand-new database (e.g. a platform restart without a disk) with the same SESSION_SECRET
    s2 = make_settings(tmp_path / "b")
    with TestClient(create_app(s2)) as c:
        c.cookies.set("md_session", token)
        assert c.get("/api/watchlists").status_code == 200
        assert c.get("/api/auth/session").json()["authenticated"] is True


def test_signout_revokes_the_cookie_server_side(owner_api):
    api, _ = owner_api
    token = _login(api)
    assert api.post("/api/auth/logout").status_code == 204
    api.c.cookies.set("md_session", token)  # replay the old cookie
    assert api.get("/api/watchlists").status_code == 401


def test_tampered_or_foreign_cookies_are_rejected(owner_api):
    api, settings = owner_api
    token = _login(api)
    payload, sig = token.split(".")
    api.c.cookies.set("md_session", payload + "." + sig[:-2] + ("AA" if not sig.endswith("AA") else "BB"))
    assert api.get("/api/watchlists").status_code == 401
    from marketdesk.services.auth import issue_session

    other, _ = issue_session(make_settings(settings.data_dir, session_secret="y" * 40), "owner")
    api.c.cookies.set("md_session", other)  # signed with a different SESSION_SECRET
    assert api.get("/api/watchlists").status_code == 401


def test_sliding_renewal_and_sign_out_everywhere(owner_api, monkeypatch):
    import time as _time

    from marketdesk.db import db_session
    from marketdesk.services.auth import revoke_all_sessions

    api, settings = owner_api
    token = _login(api)
    real = _time.time
    monkeypatch.setattr(_time, "time", lambda: real() + 2 * 86400)  # two days later
    r = api.get("/api/auth/session")
    assert r.json()["authenticated"] is True
    renewed = r.cookies.get("md_session")
    assert renewed and renewed != token  # cookie re-issued with a fresh 90-day expiry
    monkeypatch.setattr(_time, "time", real)
    with db_session() as db:
        revoke_all_sessions(db)
    api.c.cookies.set("md_session", token)
    assert api.get("/api/watchlists").status_code == 401


def test_session_lasts_90_days_by_default(owner_api):
    api, settings = owner_api
    r = api.post("/api/auth/login", json={"username": "owner", "password": OWNER_PW})
    assert f"Max-Age={90 * 24 * 3600}" in r.headers["set-cookie"]

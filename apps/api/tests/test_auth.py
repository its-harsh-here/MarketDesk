"""Authentication, CSRF, configuration safety and the read-only public demo."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marketdesk.api.app import create_app
from marketdesk.config import ConfigError, validate_settings

from .conftest import OWNER_PW, Api, make_settings, migrated


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
    validate_settings(make_settings(tmp_path, marketdesk_env="production"))


def test_dev_bypass_rejected_outside_development(tmp_path):
    for env in ("production", "test"):
        with pytest.raises(ConfigError, match="DEV_AUTH_BYPASS"):
            validate_settings(make_settings(tmp_path, marketdesk_env=env, dev_auth_bypass=True))


def test_public_demo_cannot_use_live_provider(tmp_path):
    with pytest.raises(ConfigError, match="PUBLIC_DEMO"):
        validate_settings(make_settings(tmp_path, public_demo=True, data_provider="yahoo"))


def test_public_demo_reads_but_rejects_every_write(tmp_path):
    s = migrated(make_settings(tmp_path, public_demo=True, owner_username=None, owner_password_hash=None))
    with TestClient(create_app(s)) as client:
        api = Api(client)
        sess = api.get("/api/auth/session").json()
        assert sess["read_only"] is True and sess["mode"] == "public_demo"
        assert api.get("/api/watchlists").status_code == 200
        assert api.get("/api/market/snapshots", params={"symbols": "SX:AURORA"}).status_code == 200
        writes = [
            ("post", "/api/watchlists", {"json": {"name": "x"}}),
            (
                "post",
                "/api/portfolio/transactions",
                {"json": {"type": "DEPOSIT", "effective_date": "2026-01-01", "amount": "1"}},
            ),
            ("post", "/api/alerts", {"json": {"symbol": "SX:AURORA", "direction": "ABOVE", "target_price": "1"}}),
            ("post", "/api/journal", {"json": {"symbol": "SX:AURORA", "entry_date": "2026-01-01", "title": "t"}}),
            ("patch", "/api/settings", {"json": {"theme": "light"}}),
            ("post", "/api/fixture/advance", {}),
            ("post", "/api/workspace/starter-watchlist", {}),
            ("delete", "/api/watchlists/1", {}),
        ]
        for method, url, kw in writes:
            r = getattr(api, method)(url, **kw)
            assert r.status_code == 403, url
            assert r.json()["error"]["code"] == "read_only"

"""Regression tests for the Render deploy failure: web started without a separate migrate step."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from marketdesk.api.app import create_app
from marketdesk.db import get_engine
from marketdesk.db.migrations import current_revision, ensure_migrated, head_revision

from .conftest import OWNER_PW, Api, make_settings


def test_web_start_migrates_an_empty_database_so_login_works(tmp_path):
    s = make_settings(tmp_path)  # deliberately NOT migrated, like a fresh platform disk
    assert current_revision(s.effective_database_url) is None
    with TestClient(create_app(s)) as client:
        api = Api(client)
        assert api.get("/api/readiness").json() == {"status": "ready"}
        wrong = api.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
        assert wrong.status_code == 401  # not a 500 from missing tables
        ok = api.post("/api/auth/login", json={"username": "owner", "password": OWNER_PW})
        assert ok.status_code == 200
    assert current_revision(s.effective_database_url) == head_revision()


def test_ensure_migrated_is_idempotent(tmp_path):
    s = make_settings(tmp_path)
    assert ensure_migrated(s.effective_database_url, s.data_dir) is True
    assert ensure_migrated(s.effective_database_url, s.data_dir) is False


def test_database_failure_is_an_explicit_503(tmp_path):
    s = make_settings(tmp_path)
    with TestClient(create_app(s)) as client:
        with get_engine().begin() as conn:
            conn.execute(text("DROP TABLE login_attempts"))
        r = client.post("/api/auth/login", json={"username": "owner", "password": "x"})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "database_unavailable"

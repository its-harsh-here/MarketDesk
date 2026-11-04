from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marketdesk.api.app import create_app
from marketdesk.config import REPO_ROOT, Settings
from marketdesk.db.migrations import upgrade
from marketdesk.services.auth import hash_password

OWNER_PW = "correct horse battery staple"
OWNER_HASH = hash_password(OWNER_PW)


# Set TEST_DATABASE_URL (e.g. postgresql://postgres:pw@localhost:5432/marketdesk_test) to run the whole
# suite against PostgreSQL instead of per-test SQLite files. Each settings object gets a clean schema.
PG_URL = os.environ.get("TEST_DATABASE_URL")


def _reset_postgres(url: str) -> None:
    from sqlalchemy import create_engine, text

    from marketdesk.config import normalize_database_url
    from marketdesk.db import get_engine

    try:
        get_engine().dispose()  # release pooled connections from the previous test
    except Exception:
        pass
    engine = create_engine(normalize_database_url(url))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        marketdesk_env="test",
        data_provider="fixture",
        data_dir=tmp_path,
        fixtures_dir=REPO_ROOT / "fixtures",
        owner_username="owner",
        owner_password_hash=OWNER_HASH,
        session_secret="x" * 40,
        static_dir=tmp_path / "no-static",
    )
    if PG_URL and "database_url" not in overrides:
        base["database_url"] = PG_URL
        _reset_postgres(PG_URL)
    base.update(overrides)
    return Settings(**base)


def migrated(settings: Settings) -> Settings:
    upgrade(settings.effective_database_url)
    return settings


class Api:
    """Thin TestClient wrapper that sends the CSRF header on mutations."""

    def __init__(self, client: TestClient):
        self.c = client
        self.csrf = None

    def refresh_csrf(self):
        self.csrf = self.c.get("/api/auth/session").json().get("csrf_token")

    def _h(self, extra=None):
        h = {"x-csrf-token": self.csrf or ""}
        h.update(extra or {})
        return h

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)


@pytest.fixture
def settings(tmp_path):
    return migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True))


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def api(app):
    with TestClient(app) as client:
        a = Api(client)
        a.refresh_csrf()
        yield a


@pytest.fixture
def owner_api(tmp_path):
    s = migrated(make_settings(tmp_path))
    with TestClient(create_app(s)) as client:
        yield Api(client), s


def as_revision(data: dict, revision: str, scratch_dir: Path) -> dict:
    """Rewrite a current backup as the version at `revision` would have produced it: tables and columns that did not
    exist at that revision are dropped (found by migrating an empty SQLite database to it)."""
    import json

    from sqlalchemy import create_engine, inspect

    from marketdesk.services.backup import checksum

    scratch_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{scratch_dir}/rev-{revision}.db"
    upgrade(url, revision)
    insp = inspect(create_engine(url))
    present = {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}
    old = json.loads(json.dumps(data))
    old["schema_revision"] = revision
    for name in list(old["tables"]):
        if name not in present:
            old["tables"].pop(name)
            continue
        tab = old["tables"][name]
        keep = [i for i, c in enumerate(tab["columns"]) if c in present[name]]
        tab["columns"] = [tab["columns"][i] for i in keep]
        tab["rows"] = [[row[i] for i in keep] for row in tab["rows"]]
    old["counts"] = {k: len(v["rows"]) for k, v in old["tables"].items()}
    old["checksum"] = checksum(old["tables"])
    return old

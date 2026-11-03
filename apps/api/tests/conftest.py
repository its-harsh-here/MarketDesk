from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marketdesk.api.app import create_app
from marketdesk.config import REPO_ROOT, Settings
from marketdesk.db.migrations import upgrade
from marketdesk.services.auth import hash_password

OWNER_PW = "correct horse battery staple"
OWNER_HASH = hash_password(OWNER_PW)


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

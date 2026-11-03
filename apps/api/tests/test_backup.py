"""Backup/restore through SQLite's backup API preserves the owner's records."""

from __future__ import annotations

from fastapi.testclient import TestClient

from marketdesk.api.app import create_app
from marketdesk.cli import backup_database, restore_database

from .conftest import Api, make_settings, migrated


def test_backup_and_restore_preserve_core_records(tmp_path):
    live = tmp_path / "live"
    s = migrated(make_settings(live, marketdesk_env="development", dev_auth_bypass=True))
    with TestClient(create_app(s)) as c:
        api = Api(c)
        api.refresh_csrf()
        wid = api.post("/api/watchlists", json={"name": "Keep"}).json()["id"]
        api.post(f"/api/watchlists/{wid}/items", json={"symbol": "SX:AURORA"})
        api.post("/api/portfolio/transactions", json={"type": "DEPOSIT", "effective_date": "2026-01-02",
                                                      "amount": "500"})
        api.post("/api/alerts", json={"symbol": "SX:AURORA", "direction": "BELOW", "target_price": "150"})
        api.post("/api/journal", json={"symbol": "SX:AURORA", "entry_date": "2026-01-02", "title": "Note"})
        db_path = live / "marketdesk.db"
        backup_path = tmp_path / "backups" / "b1.db"
        backup_database(db_path, backup_path)  # online, while the app holds connections (WAL mode)
        # damage live data, then restore
        api.delete(f"/api/watchlists/{wid}")
    restore_database(backup_path, db_path)
    with TestClient(create_app(s)) as c:
        api = Api(c)
        assert [w["name"] for w in api.get("/api/watchlists").json()] == ["Keep"]
        assert api.get("/api/portfolio/transactions").json()["total"] == 1
        assert len(api.get("/api/alerts").json()) == 1
        assert api.get("/api/journal").json()["total"] == 1

"""Persistence detection: anonymous container volumes must not count as a disk."""

from __future__ import annotations

from pathlib import Path

from marketdesk.services.storage import find_mount, is_persistent

ROOT = "22 1 0:21 / / rw,relatime - overlay overlay rw"
ANON = (
    "614 600 253:1 /var/lib/docker/volumes/82978c79c7e97dde59d3782d76406b9a016b26ffcf04f2ef0f015e974e163b72/_data "
    "/data rw,relatime master:1 - ext4 /dev/vda rw"
)
NAMED = "614 600 253:1 /var/lib/docker/volumes/marketdesk_marketdesk-data/_data /data rw,relatime - ext4 /dev/vda rw"
DISK = "700 600 259:3 / /data rw,relatime - ext4 /dev/nvme1n1 rw"
TMP = "701 600 0:50 / /data rw,nosuid - tmpfs tmpfs rw"


def test_anonymous_volume_is_not_persistent():
    ok, reason = is_persistent(Path("/data"), f"{ROOT}\n{ANON}\n")
    assert not ok and "anonymous" in reason


def test_named_volume_and_dedicated_disk_are_persistent():
    assert is_persistent(Path("/data"), f"{ROOT}\n{NAMED}\n")[0]
    assert is_persistent(Path("/data"), f"{ROOT}\n{DISK}\n")[0]


def test_plain_directory_and_tmpfs_are_not_persistent():
    assert not is_persistent(Path("/data"), f"{ROOT}\n")[0]
    assert not is_persistent(Path("/data"), f"{ROOT}\n{TMP}\n")[0]


def test_deepest_mount_wins_and_subdirectories_match():
    info = f"{ROOT}\n{DISK}\n" + "702 700 0:51 / /data/cache rw - tmpfs tmpfs rw\n"
    assert find_mount(Path("/data/sub/marketdesk.db"), info)["mount_point"] == "/data"
    assert find_mount(Path("/data/cache/x"), info)["fstype"] == "tmpfs"
    assert find_mount(Path("/database"), info) is None  # prefix of a different directory


def test_status_reports_storage_and_database_age(api):
    storage = api.get("/api/status").json()["storage"]
    assert set(storage) >= {"path", "persistent", "warning", "message", "database_created_at"}
    assert storage["database_created_at"] is not None
    assert storage["warning"] is False  # development never warns


def test_hosted_postgres_urls_use_the_bundled_driver():
    from marketdesk.config import normalize_database_url

    neon = "postgres://u:p@ep-x.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    assert (
        normalize_database_url(neon)
        == "postgresql+psycopg://u:p@ep-x.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    )
    assert normalize_database_url(" postgresql://u:p@h/db ") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:////data/marketdesk.db") == "sqlite:////data/marketdesk.db"


def test_external_postgres_counts_as_persistent_without_leaking_credentials(tmp_path):
    from marketdesk.api.routes_system import storage_status

    from .conftest import make_settings

    s = make_settings(tmp_path, marketdesk_env="production", database_url="postgres://user:secret@db.example.com/app")
    st = storage_status(s)
    assert st["persistent"] is True and st["warning"] is False
    assert "secret" not in st["path"] and "secret" not in st["message"] and "db.example.com" in st["path"]

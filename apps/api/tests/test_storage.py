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

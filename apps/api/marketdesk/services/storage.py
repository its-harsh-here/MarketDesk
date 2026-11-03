"""Is the database on persistent storage? Container hosts discard unmounted files on restart."""

from __future__ import annotations

import os
import re
from pathlib import Path

_ANONYMOUS_VOLUME = re.compile(r"/volumes/[0-9a-f]{64}/_data$")


def _unescape(field: str) -> str:
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def find_mount(path: Path, mountinfo: str | None) -> dict | None:
    """Return the deepest non-root mount containing `path`, from /proc/self/mountinfo text."""
    best: dict | None = None
    target = str(path)
    for line in (mountinfo or "").splitlines():
        fields = line.split()
        if len(fields) < 10 or " - " not in line:
            continue
        root, mount_point = _unescape(fields[3]), _unescape(fields[4])
        if mount_point == "/":
            continue
        if target == mount_point or target.startswith(mount_point.rstrip("/") + "/"):
            fstype = line.split(" - ", 1)[1].split()[0]
            if best is None or len(mount_point) > len(best["mount_point"]):
                best = {"mount_point": mount_point, "root": root, "fstype": fstype}
    return best


def is_persistent(path: Path, mountinfo: str | None = None) -> tuple[bool, str]:
    """(persistent?, reason). Anonymous Docker volumes and tmpfs count as not persistent."""
    if mountinfo is None:
        try:
            mountinfo = Path("/proc/self/mountinfo").read_text()
        except OSError:
            mountinfo = None
    if mountinfo is None:  # not Linux: fall back to a plain mount-point check
        probe = path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        mounted = any(os.path.ismount(p) for p in (probe, *probe.parents) if p != Path("/"))
        return mounted, "mount point" if mounted else "not a mount point"
    mount = find_mount(path, mountinfo)
    if mount is None:
        return False, "not on a mounted disk"
    if mount["fstype"] in ("tmpfs", "ramfs"):
        return False, f"{mount['mount_point']} is in memory ({mount['fstype']})"
    if _ANONYMOUS_VOLUME.search(mount["root"]):
        return False, f"{mount['mount_point']} is an anonymous container volume (discarded with the container)"
    return True, f"mounted disk at {mount['mount_point']}"

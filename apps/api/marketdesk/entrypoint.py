"""Container entrypoint: make the data directory writable, then drop root privileges.

Platform disks (Render, Fly.io) are usually mounted root-owned, while MarketDesk runs as the
unprivileged ``marketdesk`` user. When started as root this script creates ``DATA_DIR``, hands it
to that user, drops privileges and execs the given command. Started as non-root it simply execs.
Standard library only, so it adds almost no memory.

    python -m marketdesk.entrypoint <command> [args...]
"""

from __future__ import annotations

import os
import pwd
import sys

APP_USER = os.environ.get("MARKETDESK_USER", "marketdesk")


def _own_tree(path: str, uid: int, gid: int) -> None:
    for root, dirs, files in os.walk(path):
        for name in (root, *(os.path.join(root, d) for d in dirs), *(os.path.join(root, f) for f in files)):
            try:
                st = os.lstat(name)
                if st.st_uid != uid or st.st_gid != gid:
                    os.lchown(name, uid, gid)
            except OSError:
                pass


def drop_privileges() -> bool:
    """If running as root and the app user exists, fix DATA_DIR ownership and become that user."""
    if os.geteuid() != 0:
        return False
    try:
        user = pwd.getpwnam(APP_USER)
    except KeyError:
        return False  # not inside the MarketDesk image (e.g. a developer machine)
    data_dir = os.environ.get("DATA_DIR", "/data")
    os.makedirs(data_dir, exist_ok=True)
    _own_tree(data_dir, user.pw_uid, user.pw_gid)
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    os.environ["HOME"] = user.pw_dir
    os.environ["USER"] = APP_USER
    return True


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit("usage: python -m marketdesk.entrypoint <command> [args...]")
    drop_privileges()
    os.execvp(args[0], args)  # noqa: S606


if __name__ == "__main__":
    main()

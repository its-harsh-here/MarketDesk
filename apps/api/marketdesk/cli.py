"""MarketDesk operations CLI.

marketdesk migrate                    apply Alembic migrations (run once, before web/worker start)
marketdesk hash-password              print an argon2 hash for OWNER_PASSWORD_HASH (reads stdin/prompt)
marketdesk revoke-sessions            sign out every browser session
marketdesk backup PATH                consistent online SQLite backup (includes WAL contents)
marketdesk restore PATH               restore a backup (stop web and worker first)
marketdesk seed-demo                  fixture mode only: sample watchlist, portfolio, alert, journal note
marketdesk worker-health              exit 0 if the alert worker heartbeat is recent
"""

from __future__ import annotations

import argparse
import getpass
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from marketdesk.config import get_settings


def _sqlite_path() -> Path:
    url = get_settings().effective_database_url
    if not url.startswith("sqlite:///"):
        raise SystemExit("backup/restore commands support the SQLite installation only.")
    return Path(url.removeprefix("sqlite:///"))


def cmd_migrate(_: argparse.Namespace) -> None:
    from marketdesk.db.migrations import upgrade

    upgrade(get_settings().effective_database_url)
    print("migrations applied")


def cmd_preflight(_: argparse.Namespace) -> None:
    from marketdesk.config import ConfigError, validate_settings
    from marketdesk.db.migrations import upgrade

    settings = get_settings()
    try:
        validate_settings(settings)
    except ConfigError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade(settings.effective_database_url)
    print("preflight ok: settings valid, migrations applied")


def cmd_hash_password(_: argparse.Namespace) -> None:
    from marketdesk.services.auth import hash_password

    if sys.stdin.isatty():
        pw = getpass.getpass("Owner password: ")
        if pw != getpass.getpass("Repeat password: "):
            raise SystemExit("passwords did not match")
    else:
        pw = sys.stdin.readline().rstrip("\n")
    if len(pw) < 12:
        raise SystemExit("use at least 12 characters")
    print(hash_password(pw))


def cmd_revoke_sessions(_: argparse.Namespace) -> None:
    from marketdesk.db import db_session, init_engine
    from marketdesk.services.auth import revoke_all_sessions

    init_engine()
    with db_session() as db:
        revoke_all_sessions(db)
        print("all existing sign-ins revoked; every browser must sign in again (running servers apply it within 15 s)")


def backup_database(src_path: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        raise SystemExit(f"{out_path} already exists; choose a new file name")
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(out_path)
    try:
        src.backup(dst)  # SQLite online backup API: consistent snapshot including WAL frames
    finally:
        dst.close()
        src.close()


def restore_database(backup_path: Path, live_path: Path) -> None:
    check = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("backup failed integrity_check; not restoring")
        if not check.execute("SELECT name FROM sqlite_master WHERE name='alembic_version'").fetchone():
            raise SystemExit("file is not a MarketDesk database backup")
    finally:
        check.close()
    live_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(backup_path)
    dst = sqlite3.connect(live_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def cmd_backup(args: argparse.Namespace) -> None:
    backup_database(_sqlite_path(), Path(args.path))
    print(f"backup written to {args.path}")


def cmd_restore(args: argparse.Namespace) -> None:
    if not args.yes:
        answer = input("Restore replaces the current database. Web and worker must be stopped. Continue? [y/N] ")
        if answer.strip().lower() != "y":
            raise SystemExit("aborted")
    restore_database(Path(args.path), _sqlite_path())
    print("restore complete; start the services again")


def cmd_export_data(args: argparse.Namespace) -> None:
    """Consistent logical backup (SQLite or PostgreSQL) to a JSON file."""
    from marketdesk.db import init_engine
    from marketdesk.db.migrations import current_revision
    from marketdesk.services.backup import export_data

    settings = get_settings()
    out = Path(args.path)
    if out.exists():
        raise SystemExit(f"{out} already exists; choose a new file name")
    engine = init_engine(settings)
    data = export_data(engine, current_revision(settings.effective_database_url))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False))
    total = sum(data["counts"].values())
    print(f"backup written to {out}: {total} rows, checksum {data['checksum'][:12]}")


def cmd_import_data(args: argparse.Namespace) -> None:
    """Restore a JSON backup into an EMPTY database (it is migrated to the current schema first)."""
    from marketdesk.db import init_engine
    from marketdesk.db.migrations import current_revision, upgrade
    from marketdesk.services.backup import BackupError, import_data

    settings = get_settings()
    data = json.loads(Path(args.path).read_text())
    if not args.yes:
        answer = input("Restore into the configured database (it must be empty)? [y/N] ")
        if answer.strip().lower() != "y":
            raise SystemExit("aborted")
    upgrade(settings.effective_database_url)
    engine = init_engine(settings)
    try:
        counts = import_data(engine, data, current_revision(settings.effective_database_url))
    except BackupError as exc:
        raise SystemExit(f"restore refused: {exc}") from exc
    print(f"restore complete: {sum(counts.values())} rows in {sum(1 for v in counts.values() if v)} tables")


def cmd_worker_health(_: argparse.Namespace) -> None:
    from marketdesk.db import db_session, init_engine
    from marketdesk.models import WorkerStatus

    settings = get_settings()
    init_engine(settings)
    with db_session() as db:
        row = db.get(WorkerStatus, "alerts")
        limit = timedelta(seconds=max(settings.worker_heartbeat_stale_seconds, settings.alert_poll_seconds * 3))
        if row is None or row.last_cycle_at is None:
            # Allow the first cycle to complete after start-up.
            started = row.started_at if row else None
            if started and datetime.now(UTC) - started < limit:
                return
            raise SystemExit(1)
        if datetime.now(UTC) - row.last_cycle_at > limit:
            raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    # `docker compose exec web python -m marketdesk.cli ...` runs as root; act as the app user so
    # backups and database files on the volume never end up root-owned.
    from marketdesk.entrypoint import drop_privileges

    drop_privileges()
    parser = argparse.ArgumentParser(prog="marketdesk", description="MarketDesk operations")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    sub.add_parser("preflight").set_defaults(fn=cmd_preflight)
    sub.add_parser("hash-password").set_defaults(fn=cmd_hash_password)
    sub.add_parser("revoke-sessions").set_defaults(fn=cmd_revoke_sessions)
    b = sub.add_parser("backup")
    b.add_argument("path")
    b.set_defaults(fn=cmd_backup)
    r = sub.add_parser("restore")
    r.add_argument("path")
    r.add_argument("--yes", action="store_true")
    r.set_defaults(fn=cmd_restore)
    e = sub.add_parser("export-data", help="logical JSON backup (SQLite or PostgreSQL)")
    e.add_argument("path")
    e.set_defaults(fn=cmd_export_data)
    i = sub.add_parser("import-data", help="restore a JSON backup into an empty database")
    i.add_argument("path")
    i.add_argument("--yes", action="store_true")
    i.set_defaults(fn=cmd_import_data)
    sub.add_parser("worker-health").set_defaults(fn=cmd_worker_health)
    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()

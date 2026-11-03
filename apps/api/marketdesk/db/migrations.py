"""Alembic helpers used by the CLI, readiness probe and tests."""

from __future__ import annotations

import fcntl
import logging
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from marketdesk.db import make_engine

API_ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("marketdesk.migrations")


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@lru_cache(maxsize=1)
def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def current_revision(database_url: str) -> str | None:
    engine = make_engine(database_url)
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None  # no alembic_version table yet: database never migrated
    finally:
        engine.dispose()


def ensure_migrated(database_url: str, lock_dir: Path) -> bool:
    """Bring the database to head if needed. Safe to call from every process that starts.

    A file lock serialises concurrent starters (web and worker booting together), and the
    revision is re-checked under the lock, so migrations never race. Returns True if it migrated.
    """
    if current_revision(database_url) == head_revision():
        return False
    lock_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_dir / ".migrate.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            if current_revision(database_url) == head_revision():
                return False
            log.warning("database is not at the current schema revision; applying migrations")
            upgrade(database_url)
            return True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)

"""Database engine and session management (SQLite WAL for the personal install)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, exc
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from marketdesk.config import Settings, get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_read_session_factory: sessionmaker[Session] | None = None

# A pooled connection idle for longer than this is checked with a cheap query before reuse.
# (Checking every checkout, SQLAlchemy's pool_pre_ping, costs a database round trip per request.)
IDLE_PING_SECONDS = 30.0


def _sqlite_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover - exercised implicitly
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def make_engine(url: str, pool_size: int = 6, max_overflow: int = 4) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 5})
        event.listen(engine, "connect", _sqlite_pragmas)
    else:
        # Hosted Postgres (e.g. Neon's free tier) suspends idle compute and drops connections, and is
        # often a network hop away, so every round trip counts. Connections that sat idle are verified
        # before reuse (see _ping_if_idle); busy ones are not. The pool keeps enough connections for a
        # page's parallel requests (each may also use a second, short-lived session for the market-data
        # cache) so bursts reuse open TLS connections; overflow covers rare peaks. Hosted poolers such
        # as Neon's accept far more client connections than this.
        engine = create_engine(url, pool_size=pool_size, max_overflow=max_overflow, pool_timeout=30, pool_recycle=1800)
        event.listen(engine, "checkin", _mark_idle)
        event.listen(engine, "checkout", _ping_if_idle)
    return engine


def _mark_idle(_dbapi_connection, record) -> None:
    record.info["md_idle_since"] = time.monotonic()


def _ping_if_idle(dbapi_connection, record, _proxy) -> None:
    since = record.info.get("md_idle_since")
    if since is None or time.monotonic() - since < IDLE_PING_SECONDS:
        return
    try:
        # One round trip: run the ping outside a transaction (psycopg's autocommit attribute is client-side).
        dbapi_connection.autocommit = True
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SELECT 1")
        finally:
            cursor.close()
            dbapi_connection.autocommit = False
    except Exception as err:
        # The pool discards this connection and checks out a fresh one.
        raise exc.DisconnectionError() from err


def init_engine(settings: Settings | None = None) -> Engine:
    global _engine, _session_factory, _read_session_factory
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(settings.effective_database_url, settings.db_pool_size, settings.db_max_overflow)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    if _engine.dialect.name == "sqlite":
        _read_session_factory = None
    else:
        # GET requests run in autocommit mode: PostgreSQL's default READ COMMITTED isolation already
        # gives each statement its own snapshot, so this only removes the BEGIN and ROLLBACK round trips.
        # The few metadata writes a GET may make are single statements and still commit.
        _read_session_factory = sessionmaker(
            bind=_engine.execution_options(isolation_level="AUTOCOMMIT"), expire_on_commit=False, autoflush=False
        )
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one short-lived session per request (autocommit reads on PostgreSQL)."""
    factory = session_factory()
    if request.method in ("GET", "HEAD") and _read_session_factory is not None:
        factory = _read_session_factory
    db = factory()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()

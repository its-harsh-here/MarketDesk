"""Database-agnostic logical backup and restore of the owner's data.

Works the same on SQLite and PostgreSQL (Render Free has no shell and no disk, so the owner downloads the backup
from Settings or runs the CLI against a database URL):

    marketdesk export-data FILE.json          # consistent snapshot of the configured database
    marketdesk import-data FILE.json --yes    # into an EMPTY database (migrated to the same schema revision)

The export is read inside one transaction (a consistent snapshot) and contains every user table: settings,
instruments, watchlists, ledger transactions and import batches, alerts with their observations and events, and the
journal. Caches, login-attempt records and worker heartbeats are deliberately left out; they rebuild themselves.
Decimals are exported as exact strings, timestamps as ISO-8601 UTC. A SHA-256 checksum over the table data detects
truncated or edited files. Import never deletes or overwrites anything: it refuses a database that already holds
data, inserts every row in one transaction, and resets PostgreSQL id sequences afterwards.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Engine, Integer, func, insert, select, text

from marketdesk.db.types import DecimalText, UTCDateTime
from marketdesk.models import Base

FORMAT = "marketdesk-backup"
VERSION = 1
# Rebuildable or security-sensitive tables that are not part of the owner's data.
EXCLUDED_TABLES = {"market_cache", "login_attempts", "auth_sessions", "worker_status"}
# Per-database metadata that must describe the database it lives in, not the one the backup came from.
EXCLUDED_SETTINGS = {"database_created_at"}


class BackupError(RuntimeError):
    pass


def backup_tables():
    return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDED_TABLES]


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        # Canonical text, identical for SQLite (text) and PostgreSQL (NUMERIC(38,12)) storage.
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _decoder(column):
    t = column.type
    if isinstance(t, DecimalText):
        return lambda v: None if v is None else Decimal(v)
    if isinstance(t, UTCDateTime) or isinstance(t, DateTime):
        return lambda v: None if v is None else datetime.fromisoformat(v)
    if isinstance(t, Date):
        return lambda v: None if v is None else date.fromisoformat(v)
    return lambda v: v


def checksum(tables: dict) -> str:
    canonical = json.dumps(tables, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def export_data(engine: Engine, schema_revision: str | None) -> dict:
    tables: dict[str, dict] = {}
    with engine.connect() as conn:
        if engine.dialect.name == "postgresql":
            conn = conn.execution_options(isolation_level="REPEATABLE READ")
        with conn.begin():  # one snapshot for every table
            for table in backup_tables():
                columns = [c.name for c in table.columns]
                stmt = select(table)
                pk = list(table.primary_key.columns)
                if pk:
                    stmt = stmt.order_by(*pk)
                rows = []
                for row in conn.execute(stmt):
                    record = dict(row._mapping)
                    if table.name == "app_settings" and record.get("key") in EXCLUDED_SETTINGS:
                        continue
                    rows.append([_encode(record[c]) for c in columns])
                tables[table.name] = {"columns": columns, "rows": rows}
    return {
        "format": FORMAT,
        "version": VERSION,
        "schema_revision": schema_revision,
        "created_at": datetime.now(UTC).isoformat(),
        "counts": {name: len(t["rows"]) for name, t in tables.items()},
        "checksum": checksum(tables),
        "tables": tables,
    }


def validate_backup(data: Any, schema_revision: str | None) -> None:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("This file is not a MarketDesk backup.")
    if data.get("version") != VERSION:
        raise BackupError(f"Unsupported backup version {data.get('version')!r}.")
    tables = data.get("tables")
    if not isinstance(tables, dict) or checksum(tables) != data.get("checksum"):
        raise BackupError("The backup checksum does not match: the file is incomplete or was modified.")
    if data.get("schema_revision") != schema_revision:
        raise BackupError(
            f"The backup was taken at schema revision {data.get('schema_revision')!r} but this database is at "
            f"{schema_revision!r}. Restore it with the MarketDesk version that created it, then upgrade."
        )
    known = {t.name: t for t in backup_tables()}
    for name, payload in tables.items():
        if name not in known:
            raise BackupError(f"The backup contains an unknown table {name!r}.")
        expected = [c.name for c in known[name].columns]
        if payload.get("columns") != expected:
            raise BackupError(f"Columns of {name!r} do not match this schema version.")


def existing_rows(engine: Engine) -> dict[str, int]:
    counts = {}
    with engine.connect() as conn:
        for table in backup_tables():
            stmt = select(func.count()).select_from(table)
            if table.name == "app_settings":
                stmt = stmt.where(table.c.key.not_in(EXCLUDED_SETTINGS))
            n = conn.execute(stmt).scalar_one()
            if n:
                counts[table.name] = n
    return counts


def import_data(engine: Engine, data: dict, schema_revision: str | None) -> dict[str, int]:
    """Insert a validated backup into an empty database in one transaction. Returns row counts per table."""
    validate_backup(data, schema_revision)
    occupied = existing_rows(engine)
    if occupied:
        listed = ", ".join(f"{k} ({v})" for k, v in sorted(occupied.items()))
        raise BackupError(f"The target database already contains data ({listed}); restore only into an empty database.")
    inserted: dict[str, int] = {}
    with engine.begin() as conn:
        for table in backup_tables():
            payload = data["tables"].get(table.name, {"columns": [], "rows": []})
            decoders = [_decoder(table.c[name]) for name in payload["columns"]]
            records = [
                {name: dec(value) for name, dec, value in zip(payload["columns"], decoders, row, strict=True)}
                for row in payload["rows"]
            ]
            if records:
                conn.execute(insert(table), records)
            inserted[table.name] = len(records)
        if engine.dialect.name == "postgresql":
            for table in backup_tables():
                pk = list(table.primary_key.columns)
                if len(pk) == 1 and isinstance(pk[0].type, Integer):
                    col = pk[0].name
                    conn.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{col}'), "
                            f"COALESCE((SELECT MAX({col}) FROM {table.name}), 1), "
                            f"(SELECT MAX({col}) FROM {table.name}) IS NOT NULL)"
                        )
                    )
    return inserted

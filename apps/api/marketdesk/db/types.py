"""Column types that keep money exact and timestamps in UTC."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.types import TypeDecorator


class DecimalText(TypeDecorator):
    """Exact decimals. SQLite has no decimal type (NUMERIC becomes REAL), so we store text.

    On PostgreSQL this maps to NUMERIC, keeping a later migration straightforward.
    """

    impl = String(64)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Numeric(38, 12))
        return dialect.type_descriptor(String(64))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        if not value.is_finite():
            raise ValueError("Non-finite decimal values cannot be stored")
        if dialect.name == "postgresql":
            return value
        return format(value, "f")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(str(value))


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes stored as naive UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use UTC-aware values")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from marketdesk.services.prefs import display_timezone


def today_local(db: Session) -> date:
    """Today's calendar date in the owner's display timezone (used for review-due checks)."""
    return datetime.now(UTC).astimezone(ZoneInfo(display_timezone(db))).date()

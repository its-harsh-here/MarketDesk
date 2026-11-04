from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from marketdesk.api.deps import require_reader, require_writer
from marketdesk.db import get_db
from marketdesk.schemas import InboxCountsOut, InboxItemOut, InboxReadIn
from marketdesk.services import inbox as svc

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


@router.get("", response_model=list[InboxItemOut], dependencies=[Depends(require_reader)])
def list_inbox(
    type: Literal["alert", "briefing"] | None = None,  # noqa: A002 - query parameter name
    market: Literal["IN", "US"] | None = None,
    unread: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return svc.list_inbox(db, type, market, unread, limit)


@router.get("/counts", response_model=InboxCountsOut, dependencies=[Depends(require_reader)])
def counts(db: Session = Depends(get_db)):
    return svc.unread_counts(db)


@router.post("/read", dependencies=[Depends(require_writer)])
def mark_read(body: InboxReadIn, db: Session = Depends(get_db)):
    return {"updated": svc.mark_read(db, body.type, body.id)}

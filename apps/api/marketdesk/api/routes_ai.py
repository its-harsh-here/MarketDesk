"""Grok research answers: start a job, poll it, list and delete saved answers. All server-side; the key never leaves."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer
from marketdesk.api.errors import AppError
from marketdesk.asyncbridge import off_event_loop
from marketdesk.db import db_session, get_db
from marketdesk.models import AiAnswer
from marketdesk.schemas import Model
from marketdesk.services import analyst as svc
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/ai", tags=["ai"])
MAX_RUNNING = 2


class AskIn(Model):
    kind: Literal["ask", "results", "catalysts", "compare", "brief", "challenge", "briefing"]
    symbols: list[str] = Field(default_factory=list, max_length=3)
    question: str = Field(default="", max_length=500)
    journal_id: int | None = Field(default=None, description="challenge: the journal entry whose thesis is examined")


def challenge_text(entry) -> str:
    """The owner's thesis as sent to the model and kept with the answer (so the saved answer shows what it examined)."""
    parts = [f"Title: {entry.title}", f"Thesis: {entry.thesis}"]
    if entry.risks.strip():
        parts.append(f"Stated risks: {entry.risks}")
    if entry.invalidation.strip():
        parts.append(f"Invalidation conditions: {entry.invalidation}")
    if entry.decision:
        parts.append(f"Decision recorded: {entry.decision}")
    return "\n".join(parts)[: svc.CHALLENGE_MAX]


def _analyst(request: Request) -> svc.AnalystService:
    return request.app.state.analyst


@router.get("/status", dependencies=[Depends(require_reader)])
def status(request: Request, db: Session = Depends(get_db)):
    return _analyst(request).status(db)


def _start_job(app, answer_id: int) -> None:
    async def job() -> None:
        with db_session() as db:
            answer = db.get(AiAnswer, answer_id)
            if answer is not None:
                await app.state.analyst.run(db, answer, app.state.market, app.state.research)

    threading.Thread(target=lambda: asyncio.run(job()), name=f"ai-answer-{answer_id}", daemon=True).start()


@router.post("/answers", status_code=202, dependencies=[Depends(require_writer)])
@off_event_loop
async def ask(
    body: AskIn,
    request: Request,
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    analyst = _analyst(request)
    if not analyst.enabled:
        raise AppError(503, "ai_disabled", f"The AI analyst is unavailable. {analyst.problem}")
    question = body.question
    if body.kind == "challenge":
        from marketdesk.models import JournalEntry

        entry = db.get(JournalEntry, body.journal_id) if body.journal_id else None
        if entry is None:
            raise AppError(404, "not_found", "That journal entry no longer exists.")
        if not entry.thesis.strip():
            raise AppError(422, "validation_error", "Write a thesis in this entry before asking for a challenge.")
        body = body.model_copy(update={"symbols": [entry.instrument.symbol]})
        question = challenge_text(entry)
    analyst.validate_request(body.kind, body.symbols, question)
    analyst.recover_stale(db)
    running = db.scalar(select(func.count()).select_from(AiAnswer).where(AiAnswer.status == "running")) or 0
    if running >= MAX_RUNNING:
        raise AppError(429, "busy", "Research answers are already running; wait for them to finish.")
    symbols = []
    for s in body.symbols:
        inst = await resolve_instrument(db, market, s)
        if inst.symbol not in symbols:
            symbols.append(inst.symbol)
    analyst.validate_request(body.kind, symbols, question)
    a = AiAnswer(
        day=datetime.now(UTC).date(),
        kind=body.kind,
        symbols=symbols,
        question=question.strip(),
        status="running",
        steps=[{"at": datetime.now(UTC).isoformat(), "text": "Queued."}],
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    _start_job(request.app, a.id)
    return svc.answer_dict(a)


@router.get("/answers", dependencies=[Depends(require_reader)])
def list_answers(
    symbol: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    rows = list(db.scalars(select(AiAnswer).order_by(AiAnswer.created_at.desc()).limit(200)))
    if symbol:
        rows = [r for r in rows if symbol.upper() in r.symbols]
    return [svc.answer_dict(r, full=False) for r in rows[:limit]]


@router.get("/answers/{aid}", dependencies=[Depends(require_reader)])
def get_answer(aid: int, db: Session = Depends(get_db)):
    a = db.get(AiAnswer, aid)
    if a is None:
        raise AppError(404, "not_found", "Answer not found.")
    return svc.answer_dict(a)


@router.delete("/answers/{aid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_answer(aid: int, db: Session = Depends(get_db)):
    a = db.get(AiAnswer, aid)
    if a is None:
        raise AppError(404, "not_found", "Answer not found.")
    if a.status == "running":
        raise AppError(409, "running", "This answer is still running.")
    db.delete(a)
    db.commit()
    return Response(status_code=204)

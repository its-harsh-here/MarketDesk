"""Streaming quotes (roadmap M04): Server-Sent Events relaying Alpaca IEX trades for US listings."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from marketdesk.api.deps import require_reader
from marketdesk.providers.alpaca import us_symbol

router = APIRouter(prefix="/api/stream", tags=["stream"], dependencies=[Depends(require_reader)])

HEARTBEAT_SECONDS = 15.0
MAX_CONNECTION_SECONDS = 30 * 60  # the browser's EventSource reconnects on its own


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.get("/status")
async def stream_status(request: Request) -> dict:
    """Feed name, connection state and drop counters of the quote stream."""
    hub = request.app.state.stream
    return {**hub.snapshot_status(), "available": hub.unavailable_reason() is None,
            "reason": hub.unavailable_reason()}  # fmt: skip


@router.get("/quotes", response_class=StreamingResponse)
async def stream_quotes(request: Request, symbols: str = Query(min_length=1, max_length=600)):
    """text/event-stream of `status` and `trades` events for up to 30 US symbols (others are reported as polled)."""
    hub = request.app.state.stream
    asked = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))[:60]
    alias = {a: s for s in asked if (a := us_symbol(s))}  # Alpaca symbol → the page's symbol (BRK.B → BRK-B)
    reason = hub.unavailable_reason()

    async def body():
        if reason is not None:
            yield _event("status", {**hub.snapshot_status(), "status": "off", "message": reason, "streamed": [],
                                    "polled": asked})  # fmt: skip
            return
        streamed, refused = hub.acquire(list(alias))
        page_streamed = [alias[a] for a in streamed]
        polled = [s for s in asked if s not in page_streamed]
        wanted = set(streamed)
        try:
            last_seq, last_status, last_beat = 0, -1, time.monotonic()
            started = time.monotonic()
            note = {"streamed": page_streamed, "polled": polled, "over_limit": [alias[a] for a in refused]}
            while time.monotonic() - started < MAX_CONNECTION_SECONDS:
                if await request.is_disconnected():
                    break
                if hub.status_seq != last_status:
                    last_status = hub.status_seq
                    yield _event("status", {**hub.snapshot_status(), **note})
                    last_beat = time.monotonic()
                ticks, last_seq = hub.since(last_seq, wanted)
                if ticks:
                    ticks = [{**t, "symbol": alias[t["symbol"]]} for t in ticks]
                    yield _event("trades", {"feed": "iex", "trades": ticks})
                    last_beat = time.monotonic()
                elif time.monotonic() - last_beat > HEARTBEAT_SECONDS:
                    yield ": keep-alive\n\n"
                    last_beat = time.monotonic()
                await asyncio.sleep(1.0)
        finally:
            hub.release(streamed)

    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    return StreamingResponse(body(), media_type="text/event-stream", headers=headers)

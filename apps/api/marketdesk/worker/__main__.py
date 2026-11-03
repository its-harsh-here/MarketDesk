"""Alert worker: a single process that samples quotes and evaluates alerts.

Run exactly one instance (compose service ``worker``). Web processes never schedule jobs.
    python -m marketdesk.worker            # loop forever
    python -m marketdesk.worker --once     # one evaluation cycle (deterministic tests)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import UTC, datetime

from marketdesk.config import get_settings, validate_settings
from marketdesk.db import db_session, init_engine, session_factory
from marketdesk.models import WorkerStatus
from marketdesk.services.alerts import run_evaluation_cycle
from marketdesk.services.runtime import build_market_service

log = logging.getLogger("marketdesk.worker")
WORKER_NAME = "alerts"


def _status(db, provider: str) -> WorkerStatus:
    row = db.get(WorkerStatus, WORKER_NAME)
    if row is None:
        row = WorkerStatus(name=WORKER_NAME, provider=provider, started_at=datetime.now(UTC), cycles=0)
        db.add(row)
        db.commit()
    return row


async def run_cycle(market) -> dict:
    with db_session() as db:
        row = _status(db, market.source)
        try:
            summary = await run_evaluation_cycle(db, market)
            row.last_success_at = datetime.now(UTC)
            row.last_error = None
        except Exception as exc:  # keep the worker alive; record a sanitized reason
            log.exception("evaluation cycle failed")
            summary = {"error": type(exc).__name__}
            row.last_error = f"Evaluation failed ({type(exc).__name__})."
        skipped = summary.get("skipped") or []
        if skipped and not row.last_error:
            row.last_error = f"{len(skipped)} symbol(s) skipped: provider data was stale or unavailable."
        row.last_cycle_at = datetime.now(UTC)
        row.cycles = (row.cycles or 0) + 1
        row.provider = market.source
        row.last_summary = summary
        db.commit()
        return summary


async def main_async(once: bool) -> None:
    settings = get_settings()
    validate_settings(settings)
    init_engine(settings)
    market = build_market_service(settings, session_factory())
    with db_session() as db:
        row = _status(db, market.source)
        row.started_at = datetime.now(UTC)
        db.commit()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover
            pass
    while True:
        summary = await run_cycle(market)
        log.info("cycle: %s", {k: v for k, v in summary.items() if k != "skipped"})
        if once:
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.alert_poll_seconds)
            return
        except TimeoutError:
            continue


def main() -> None:
    parser = argparse.ArgumentParser(description="MarketDesk alert worker")
    parser.add_argument("--once", action="store_true", help="run a single evaluation cycle and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main_async(args.once))


if __name__ == "__main__":
    main()

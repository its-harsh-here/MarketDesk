"""Alert worker: a single process that samples quotes and evaluates alerts.

Run exactly one instance (compose service ``worker``). Web processes never schedule jobs.
    python -m marketdesk.worker            # loop forever
    python -m marketdesk.worker --once     # one evaluation cycle (deterministic tests)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from datetime import UTC, datetime

from marketdesk import memory
from marketdesk.config import get_settings, validate_settings
from marketdesk.db import db_session, init_engine, session_factory
from marketdesk.models import WorkerStatus
from marketdesk.services.alerts import run_evaluation_cycle
from marketdesk.services.briefings import run_due_briefings
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


async def _refresh_research(market) -> dict:
    """Daily filing checks for watchlisted US companies (SEC); isolated so it can never stop alert evaluation."""
    from marketdesk.services.research import ResearchService

    def run():
        with db_session() as db:
            return ResearchService(market.settings).refresh_tracked(db)

    try:
        return await asyncio.to_thread(run)
    except Exception as exc:  # never let research refresh break the alert worker
        log.warning("research refresh failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}


async def _briefings(market) -> dict:
    """Morning / end-of-session briefings that are due by the exchange calendars (idempotent per session)."""
    try:
        with db_session() as db:
            return await run_due_briefings(db, market)
    except Exception as exc:  # never let briefing generation break the alert worker
        log.warning("briefing generation failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}


async def _screener_snapshots(market) -> dict:
    """A few stale screening snapshots per cycle (watchlists, holdings, lists, peers), so screens stay current."""
    from marketdesk.services.screener import refresh_instruments, tracked_instruments

    s = market.settings
    try:
        with db_session() as db:
            insts = tracked_instruments(db, market.source, s.screener_max_universe)
            return await refresh_instruments(db, market, insts, hours=s.screener_snapshot_hours,
                                             limit=s.screener_refresh_per_cycle)  # fmt: skip
    except Exception as exc:  # never let snapshot refresh break the alert worker
        log.warning("screener refresh failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}


def mark_started(provider: str) -> None:
    with db_session() as db:
        row = _status(db, provider)
        row.started_at = datetime.now(UTC)
        db.commit()


async def run_cycle(market, research=None, embedded: bool = False) -> dict:
    from marketdesk.services.research import ResearchService

    research = research or ResearchService(market.settings)
    with db_session() as db:
        row = _status(db, market.source)
        try:
            summary = await run_evaluation_cycle(db, market, research)
            row.last_success_at = datetime.now(UTC)
            row.last_error = None
        except Exception as exc:  # keep the worker alive; record a sanitized reason
            log.exception("evaluation cycle failed")
            summary = {"error": type(exc).__name__}
            row.last_error = f"Evaluation failed ({type(exc).__name__})."
        summary["research"] = await _refresh_research(market)
        summary["briefings"] = await _briefings(market)
        summary["screener"] = await _screener_snapshots(market)
        memory.trim(min_interval=0)  # give back what the cycle used before reporting
        summary["memory"] = {"rss_mb": memory.rss_mb(), "peak_mb": memory.peak_mb(), "embedded": embedded}
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
    # The worker needs few database connections and threads (docs/PERFORMANCE_ROADMAP.md).
    settings = get_settings().model_copy(update={"db_pool_size": 2, "db_max_overflow": 1})
    from marketdesk.asyncbridge import SHARED_EXECUTOR, configure_threads
    from marketdesk.services.alerts import configure_channels

    configure_threads(4)
    asyncio.get_running_loop().set_default_executor(SHARED_EXECUTOR)

    configure_channels(settings)
    validate_settings(settings, role="worker")
    init_engine(settings)
    from marketdesk.db.migrations import ensure_migrated

    ensure_migrated(settings.effective_database_url, settings.data_dir)
    market = build_market_service(settings, session_factory())
    from marketdesk.services.research import ResearchService

    research = ResearchService(settings)  # one client, so its SEC request pacing spans cycles
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
    from marketdesk.worker.embedded import acquire_lease, holder_id

    holder = holder_id()
    while True:
        # The same single-runner lease as the embedded worker: never two evaluators at once.
        if not await asyncio.to_thread(acquire_lease, holder, max(30, settings.alert_poll_seconds) * 3):
            log.info("another process holds the worker lease; waiting")
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.alert_poll_seconds)
                return
            except TimeoutError:
                continue
        summary = await run_cycle(market, research)
        log.info("cycle: %s", {k: v for k, v in summary.items() if k != "skipped"})
        if once:
            return
        rss = memory.rss_mb()
        if os.environ.get("MARKETDESK_SUPERVISED") == "1" and rss > settings.worker_memory_soft_limit_mb:
            log.warning("worker memory %.0f MB above the %d MB soft limit: exiting for a clean restart",
                        rss, settings.worker_memory_soft_limit_mb)  # fmt: skip
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

"""FastAPI application factory. Serves /api routes and, when built, the SPA on the same origin."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import signal
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from marketdesk import __version__, memory
from marketdesk.api import (
    routes_ai,
    routes_alerts,
    routes_earnings,
    routes_inbox,
    routes_journal,
    routes_lab,
    routes_macro,
    routes_market,
    routes_performance,
    routes_portfolio,
    routes_research,
    routes_screener,
    routes_stream,
    routes_system,
    routes_terminal,
    routes_valuation,
    routes_watchlists,
    routes_workspace,
    timing,
)
from marketdesk.api.errors import error_body, install_error_handlers
from marketdesk.config import REPO_ROOT, Settings, get_settings, validate_settings
from marketdesk.db import init_engine, session_factory
from marketdesk.providers.finra import FinraClient
from marketdesk.services.market import MarketDataService
from marketdesk.services.runtime import build_market_service

log = logging.getLogger("marketdesk")
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{8,64}")


def _configure_logging() -> None:
    """Make marketdesk.* INFO lines (failures with request IDs, sign-in outcomes) visible in the host's logs."""
    if log.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'sha256-REPLACED_AT_BUILD'; font-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


def _stamp_database_created() -> None:
    """Remember when this database was first used, so a reset (lost storage) is visible in Settings."""
    from datetime import UTC, datetime

    from marketdesk.db import db_session
    from marketdesk.models import AppSetting

    with db_session() as db:
        if db.get(AppSetting, "database_created_at") is None:
            db.add(AppSetting(key="database_created_at", value=datetime.now(UTC).isoformat()))
            db.commit()


def _static_dir(settings: Settings) -> Path | None:
    candidate = settings.static_dir or (REPO_ROOT / "apps" / "web" / "dist")
    return candidate if (candidate / "index.html").exists() else None


def create_app(settings: Settings | None = None, market: MarketDataService | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging()
    validate_settings(settings)
    init_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Hosts that only run the web command (no separate migrate step) still get a working schema.
        from marketdesk.db.migrations import ensure_migrated

        ensure_migrated(settings.effective_database_url, settings.data_dir)
        _stamp_database_created()
        from marketdesk.asyncbridge import SHARED_EXECUTOR, configure_threads

        configure_threads(settings.blocking_threads)
        asyncio.get_running_loop().set_default_executor(SHARED_EXECUTOR)
        import marketdesk.asyncbridge as bridge

        bridge._home_loop = asyncio.get_running_loop()  # noqa: SLF001 - the worker thread forwards market calls here
        embedded = None
        if settings.embedded_worker:
            from marketdesk.worker.embedded import EmbeddedWorker

            delay = float(os.environ.get("WORKER_START_DELAY_SECONDS", "45"))
            embedded = EmbeddedWorker(app.state, settings, start_delay=delay)
            embedded.start()
            app.state.embedded_worker = embedded
        warm = getattr(app.state.market.provider, "warm", None)
        if warm is not None:  # load the market-data library without delaying the first page
            threading.Thread(target=warm, name="provider-warm", daemon=True).start()
        yield
        if embedded is not None:
            await asyncio.to_thread(embedded.stop)

    app = FastAPI(
        title="MarketDesk API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
    )
    app.state.settings = settings
    from marketdesk.services.alerts import configure_channels

    configure_channels(settings)
    app.state.market = market or build_market_service(settings, session_factory())
    from marketdesk.services.research import ResearchService

    app.state.research = ResearchService(settings)
    from marketdesk.services.analyst import AnalystService

    app.state.analyst = AnalystService(settings)
    app.state.finra = FinraClient(settings.finra_client_id, settings.finra_client_secret)
    from marketdesk.providers.fred import FredClient

    app.state.fred = FredClient(settings.fred_api_key)
    from marketdesk.providers.alpaca import AlpacaClient
    from marketdesk.providers.gnews import GoogleNews
    from marketdesk.services.stream import QuoteStreamHub

    app.state.gnews = GoogleNews()
    app.state.alpaca = AlpacaClient(settings.alpaca_api_key_id, settings.alpaca_api_secret_key)
    app.state.stream = QuoteStreamHub(app.state.alpaca, enabled=settings.alpaca_streaming
                                      and settings.data_provider == "yahoo")  # fmt: skip
    install_error_handlers(app)

    if settings.extra_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.extra_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["content-type", "x-csrf-token"],
        )

    static = _static_dir(settings)
    csp_hash = None
    if static is not None:
        hash_file = static / "csp-hash.txt"
        csp_hash = hash_file.read_text().strip() if hash_file.exists() else None

    timing.install_db_listeners()

    def _account_memory(request: Request, before: float, ms: float) -> None:
        """Record growth per route, give memory back after growth, and restart gracefully above the soft limit."""
        route = request.scope.get("route")
        name = f"{request.method} {getattr(route, 'path', request.url.path)}"
        after = memory.rss_mb()
        memory.ROUTES.record(name, after - before, ms)
        app.state.api_requests += 1
        if after - before > 4 or after > settings.web_memory_soft_limit_mb * 0.85 or app.state.api_requests % 25 == 0:
            memory.trim()
            after = memory.rss_mb()
        supervised = os.environ.get("MARKETDESK_SUPERVISED") == "1"  # only under marketdesk.serve, which restarts it
        if supervised and after > settings.web_memory_soft_limit_mb and not app.state.restart_requested:
            app.state.restart_requested = True
            log.warning("web memory %.0f MB above the %d MB soft limit: restarting gracefully",
                        after, settings.web_memory_soft_limit_mb)  # fmt: skip
            # uvicorn finishes in-flight requests on SIGTERM; the supervisor (marketdesk.serve) starts a new process
            signal.raise_signal(signal.SIGTERM)

    app.state.restart_requested = False
    app.state.api_inflight = 0
    app.state.embedded_worker = None
    app.state.api_requests = 0

    from marketdesk.services.viewcache import VIEWS

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        started = time.perf_counter()
        timings = timing.start()
        # Request ID: reuse a well-formed upstream ID (e.g. from a proxy), otherwise create one. Returned in the
        # X-Request-ID header and in error bodies, and written on server-side failure log lines.
        inbound = request.headers.get("x-request-id", "")
        request.state.request_id = inbound if _REQUEST_ID_RE.fullmatch(inbound) else secrets.token_hex(8)
        is_api = request.url.path.startswith("/api/")
        before = memory.rss_mb() if is_api else 0.0
        if is_api:
            app.state.api_inflight += 1
        try:
            response = await call_next(request)
        finally:
            if is_api:
                app.state.api_inflight -= 1
        response.headers["X-Request-ID"] = request.state.request_id
        if is_api and request.method in ("POST", "PUT", "PATCH", "DELETE") and response.status_code < 400:
            VIEWS.clear()  # a change by the user: no assembled view from before it may be served (roadmap 3.4)
        if before and not request.url.path.startswith("/api/stream"):
            _account_memory(request, before, (time.perf_counter() - started) * 1000)
        if request.url.path.startswith("/api/"):
            response.headers["Server-Timing"] = timing.header(timings, (time.perf_counter() - started) * 1000)
        for k, v in SECURITY_HEADERS.items():
            if k == "Content-Security-Policy":
                v = v.replace("'sha256-REPLACED_AT_BUILD'", f"'{csp_hash}'" if csp_hash else "")
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        elif request.url.path.startswith("/assets/") and response.status_code == 200:
            # Build output with content hashes in the file names: safe to cache for a year (roadmap 4.1).
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    for r in (
        routes_system,
        routes_market,
        routes_research,
        routes_watchlists,
        routes_portfolio,
        routes_alerts,
        routes_ai,
        routes_inbox,
        routes_journal,
        routes_screener,
        routes_performance,
        routes_valuation,
        routes_earnings,
        routes_macro,
        routes_lab,
        routes_workspace,
        routes_terminal,
        routes_stream,
    ):
        app.include_router(r.router)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def api_not_found(path: str):
        return JSONResponse(error_body("not_found", "No such API route."), status_code=404)

    if static is not None:
        assets = static / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")
        index = static / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            candidate = (static / path).resolve()
            if path and candidate.is_file() and static.resolve() in candidate.parents:
                if path in ("sw.js", "manifest.webmanifest"):  # always revalidated, so updates arrive promptly
                    media = "application/manifest+json" if path.endswith(".webmanifest") else "text/javascript"
                    return FileResponse(candidate, media_type=media, headers={"Cache-Control": "no-cache"})
                return FileResponse(candidate)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app

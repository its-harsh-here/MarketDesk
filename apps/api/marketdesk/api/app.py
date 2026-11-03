"""FastAPI application factory. Serves /api routes and, when built, the SPA on the same origin."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from marketdesk import __version__
from marketdesk.api import (
    routes_alerts,
    routes_journal,
    routes_market,
    routes_portfolio,
    routes_system,
    routes_watchlists,
)
from marketdesk.api.errors import error_body, install_error_handlers
from marketdesk.config import REPO_ROOT, Settings, get_settings, validate_settings
from marketdesk.db import init_engine, session_factory
from marketdesk.services.market import MarketDataService
from marketdesk.services.runtime import build_market_service

log = logging.getLogger("marketdesk")

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


def _static_dir(settings: Settings) -> Path | None:
    candidate = settings.static_dir or (REPO_ROOT / "apps" / "web" / "dist")
    return candidate if (candidate / "index.html").exists() else None


def create_app(settings: Settings | None = None, market: MarketDataService | None = None) -> FastAPI:
    settings = settings or get_settings()
    validate_settings(settings)
    init_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(
        title="MarketDesk API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
    )
    app.state.settings = settings
    app.state.market = market or build_market_service(settings, session_factory())
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

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            if k == "Content-Security-Policy":
                v = v.replace("'sha256-REPLACED_AT_BUILD'", f"'{csp_hash}'" if csp_hash else "")
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for r in (routes_system, routes_market, routes_watchlists, routes_portfolio, routes_alerts, routes_journal):
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
                return FileResponse(candidate)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app

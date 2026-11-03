from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from marketdesk import __version__
from marketdesk.api.deps import current_principal, market_dep, require_reader, require_writer, settings_dep
from marketdesk.api.errors import AppError
from marketdesk.api.routes_market import benchmark_symbols
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.models import AppSetting, Watchlist, WorkerStatus
from marketdesk.providers.fixture import FixtureState
from marketdesk.schemas import (
    BriefingOut,
    FixtureStateOut,
    LoginIn,
    PrefsOut,
    PrefsPatch,
    SessionOut,
    StatusOut,
    WatchlistOut,
)
from marketdesk.services import auth
from marketdesk.services import watchlists as wl_svc
from marketdesk.services.briefing import build_briefing
from marketdesk.services.clock import today_local
from marketdesk.services.market import MarketDataService
from marketdesk.services.prefs import get_prefs, read_fixture_state, update_prefs, write_fixture_state
from marketdesk.services.storage import is_persistent

router = APIRouter(prefix="/api", tags=["system"])

ATTRIBUTION = [
    {
        "name": "TradingView Lightweight Charts",
        "license": "Apache-2.0",
        "url": "https://www.tradingview.com/lightweight-charts/",
        "note": (
            "TradingView Lightweight Charts™ — Copyright © TradingView, Inc. https://www.tradingview.com/. "
            "Each chart also shows the TradingView attribution logo linking to tradingview.com."
        ),
    },
    {
        "name": "yfinance (unofficial Yahoo Finance access)",
        "license": "Apache-2.0",
        "url": "https://ranaroussi.github.io/yfinance/",
        "note": "Live mode reads Yahoo Finance data through yfinance, which is not affiliated with Yahoo. "
        "Yahoo data is for personal use; review Yahoo's terms before redistribution.",
    },
    {
        "name": "Inter and JetBrains Mono typefaces",
        "license": "SIL Open Font License 1.1",
        "url": "https://fontsource.org/",
        "note": "Bundled locally through Fontsource.",
    },
    {"name": "Lucide icons", "license": "ISC", "url": "https://lucide.dev/", "note": "Interface icons."},
]


def storage_status(settings: Settings, db: Session | None = None) -> dict:
    """Is the database on persistent storage? Container hosts discard unmounted files on restart."""
    path = settings.data_dir.resolve()
    if not settings.uses_sqlite:
        url = make_url(settings.effective_database_url)
        where = f"{url.get_backend_name()}://{url.host or 'localhost'}/{url.database or ''}"
        created = None
        if db is not None:
            row = db.get(AppSetting, "database_created_at")
            created = row.value if row is not None else None
        return {
            "path": where,
            "persistent": True,
            "warning": False,
            "message": f"Data is stored in an external PostgreSQL database ({where}); it survives restarts.",
            "database_created_at": created,
        }
    persistent, reason = is_persistent(path)
    created = None
    if db is not None:
        row = db.get(AppSetting, "database_created_at")
        created = row.value if row is not None else None
    if persistent:
        message = f"Database and sign-in data are stored on a {reason}."
    elif settings.is_production:
        message = (
            f"{path}: {reason}. Watchlists, transactions, alerts and journal notes are lost on every restart or "
            "redeploy. Attach a persistent disk mounted at this path."
        )
    else:
        message = f"Database stored at {path} (local directory)."
    return {
        "path": str(path),
        "persistent": persistent,
        "warning": bool(settings.is_production and not persistent),
        "message": message,
        "database_created_at": created,
    }


def worker_status(db: Session, settings: Settings) -> dict:
    row = db.get(WorkerStatus, "alerts")
    if row is None or row.last_cycle_at is None:
        return {
            "running": False,
            "stale": True,
            "poll_seconds": settings.alert_poll_seconds,
            "cycles": 0,
            "message": "The alert worker has not reported yet. Alerts are only evaluated while the worker runs.",
        }
    age = (datetime.now(UTC) - row.last_cycle_at).total_seconds()
    stale = age > max(settings.worker_heartbeat_stale_seconds, settings.alert_poll_seconds * 3)
    message = (
        "Worker heartbeat is overdue; alerts are not being evaluated."
        if stale
        else "Worker is evaluating alerts at its polling interval (sampled detection)."
    )
    return {
        "running": not stale,
        "stale": stale,
        "provider": row.provider,
        "started_at": row.started_at,
        "last_cycle_at": row.last_cycle_at,
        "last_success_at": row.last_success_at,
        "last_error": row.last_error,
        "cycles": row.cycles,
        "poll_seconds": settings.alert_poll_seconds,
        "last_summary": row.last_summary,
        "message": message,
    }


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/readiness")
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:
        raise AppError(503, "not_ready", "Database is not ready or migrations have not been applied.") from exc
    from marketdesk.db.migrations import head_revision

    if version != head_revision():
        raise AppError(503, "not_ready", "Database migrations are not at the expected revision.")
    return {"status": "ready"}


@router.get("/status", response_model=StatusOut)
def status(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    market: MarketDataService = Depends(market_dep),
    _=Depends(require_reader),
):
    sample = market.source == "fixture"
    dataset_date = None
    disclaimer = None
    if sample:
        dataset_date = market.provider.cursor_date(read_fixture_state(db))
        disclaimer = market.provider.dataset.meta["disclaimer"]
    return {
        "version": __version__,
        "environment": settings.marketdesk_env,
        "provider": market.source,
        "sample_data": sample,
        "dataset_date": dataset_date,
        "dataset_disclaimer": disclaimer,
        "read_only": False,
        "auth_mode": settings.auth_mode,
        "market_status": (
            "Sample dataset — no live trading session"
            if sample
            else "Market status unavailable (no verified exchange calendar)"
        ),
        "provider_health": market.health(),
        "worker": worker_status(db, settings),
        "storage": storage_status(settings, db),
        "benchmarks": benchmark_symbols(settings, market),
        "attribution": ATTRIBUTION,
    }


# ----------------------------------------------------------------------------- auth
def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.effective_cookie_secure,
        path="/",
    )


@router.get("/auth/session", response_model=SessionOut)
def session(response: Response, settings: Settings = Depends(settings_dep), principal=Depends(current_principal)):
    if principal is None:
        return {"authenticated": False, "mode": "owner", "read_only": False}
    if principal.mode == "owner" and principal.claims and auth.needs_refresh(principal.claims):
        # Sliding expiry: while you keep using MarketDesk, the sign-in keeps renewing.
        token, _ = auth.issue_session(
            settings, principal.username, csrf=principal.claims["csrf"], sid=principal.claims["sid"]
        )
        _set_session_cookie(response, settings, token)
    return {
        "authenticated": True,
        "mode": principal.mode,
        "username": principal.username,
        "csrf_token": principal.csrf_token,
        "read_only": principal.read_only,
    }


@router.post("/auth/login", response_model=SessionOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
):
    if settings.auth_mode != "owner":
        raise AppError(400, "login_not_required", "Login is not used in this mode.")
    key = auth.client_key(settings, request.client.host if request.client else None)
    retry = auth.login_blocked(db, settings, key)
    if retry:
        raise AppError(
            429,
            "rate_limited",
            "Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(retry)},
        )
    if not auth.verify_credentials(settings, body.username, body.password):
        auth.record_attempt(db, key, False)
        raise AppError(401, "invalid_credentials", "Incorrect username or password.")
    auth.record_attempt(db, key, True)
    token, claims = auth.issue_session(settings, settings.owner_username or body.username)
    _set_session_cookie(response, settings, token)
    return {
        "authenticated": True,
        "mode": "owner",
        "username": claims["u"],
        "csrf_token": claims["csrf"],
        "read_only": False,
    }


@router.post("/auth/logout", status_code=204)
def logout(response: Response, db: Session = Depends(get_db), principal=Depends(require_writer)):
    if principal.claims:
        auth.revoke_session(db, principal.claims)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    response.status_code = 204
    return response


# ----------------------------------------------------------------------------- prefs & briefing
@router.get("/settings", response_model=PrefsOut, dependencies=[Depends(require_reader)])
def get_settings_route(db: Session = Depends(get_db)):
    return get_prefs(db)


@router.patch("/settings", response_model=PrefsOut, dependencies=[Depends(require_writer)])
def patch_settings(body: PrefsPatch, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    patch = body.model_dump(exclude_unset=True)
    if patch.get("chart_symbol"):
        try:
            patch["chart_symbol"] = market.validate_symbol(patch["chart_symbol"])
        except Exception as exc:
            raise AppError(422, "unsupported_symbol", "Chart symbol is not supported by the current provider.") from exc
    return update_prefs(db, patch)


@router.get("/briefing", response_model=BriefingOut, dependencies=[Depends(require_reader)])
async def briefing(db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return await build_briefing(db, market, today_local(db))


# ----------------------------------------------------------------------------- fixture harness (development/test only)
def _fixture_out(market: MarketDataService, db: Session) -> dict:
    if market.source != "fixture":
        return {"enabled": False}
    state = read_fixture_state(db)
    ds = market.provider.dataset
    return {
        "enabled": True,
        "cursor_index": state.cursor_index,
        "cursor_date": market.provider.cursor_date(state),
        "base_date": ds.base_date,
        "sessions": ds.session_dates(),
        "fault": state.fault,
    }


def _require_fixture(market: MarketDataService) -> None:
    if market.source != "fixture":
        raise AppError(404, "not_found", "Sample replay controls exist only in fixture mode.")


@router.get("/fixture", response_model=FixtureStateOut, dependencies=[Depends(require_reader)])
def fixture_state(db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return _fixture_out(market, db)


@router.post("/fixture/advance", response_model=FixtureStateOut, dependencies=[Depends(require_writer)])
def fixture_advance(db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    _require_fixture(market)
    state = read_fixture_state(db)
    last = len(market.provider.dataset.session_dates()) - 1
    if state.cursor_index >= last:
        raise AppError(409, "end_of_dataset", "The sample dataset has no further sessions to replay.")
    write_fixture_state(db, FixtureState(state.cursor_index + 1, state.fault))
    market.invalidate()
    return _fixture_out(market, db)


@router.post("/fixture/reset", response_model=FixtureStateOut, dependencies=[Depends(require_writer)])
def fixture_reset(db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    _require_fixture(market)
    write_fixture_state(db, FixtureState(0, False))
    market.invalidate()
    market.reset_circuit()
    return _fixture_out(market, db)


@router.post("/fixture/fault", response_model=FixtureStateOut, dependencies=[Depends(require_writer)])
def fixture_fault(enabled: bool, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    _require_fixture(market)
    state = read_fixture_state(db)
    write_fixture_state(db, FixtureState(state.cursor_index, enabled))
    if not enabled:
        market.reset_circuit()
        market.invalidate()
    return _fixture_out(market, db)


# ----------------------------------------------------------------------------- explicit starter workspace
def _starter_symbols(settings: Settings, market: MarketDataService) -> list[str]:
    if market.source == "fixture":
        return list(market.provider.dataset.starter_watchlist)
    cfg = json.loads((settings.starter_config_dir / "starter_watchlist.yahoo.json").read_text())
    return [s for s in cfg["symbols"] if not s.startswith("^")]


@router.post(
    "/workspace/starter-watchlist", response_model=WatchlistOut, status_code=201, dependencies=[Depends(require_writer)]
)
async def starter_watchlist(
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    market: MarketDataService = Depends(market_dep),
):
    name = "Sample starter" if market.source == "fixture" else "NSE starter"
    if db.query(Watchlist).filter(Watchlist.name == name).first():
        raise AppError(409, "duplicate_name", f"A watchlist named '{name}' already exists.")
    w = wl_svc.create_watchlist(db, settings, name)
    failures = []
    for sym in _starter_symbols(settings, market):
        try:
            await wl_svc.add_symbol(db, settings, market, w.id, sym)
        except AppError as err:
            failures.append(f"{sym}: {err.message}")
    db.refresh(w)
    out = wl_svc.watchlist_dict(w)
    if failures and not w.items:
        raise AppError(
            503,
            "starter_failed",
            "No starter symbols could be verified with the provider.",
            {"failures": failures[:10]},
        )
    return out

"""Request dependencies: settings, DB, market service and the auth/CSRF/read-only gates."""

from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.config import Settings, get_settings
from marketdesk.db import get_db
from marketdesk.services.auth import (
    COOKIE_NAME,
    Principal,
    dev_bypass_principal,
    lookup_session,
)
from marketdesk.services.market import MarketDataService


def settings_dep(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


def market_dep(request: Request) -> MarketDataService:
    return request.app.state.market


def current_principal(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)
) -> Principal | None:
    if settings.dev_auth_bypass and settings.marketdesk_env == "development":
        return dev_bypass_principal(settings)
    row = lookup_session(db, settings, request.cookies.get(COOKIE_NAME))
    if row is None:
        return None
    return Principal("owner", row.username, row.csrf_token, False, row.id)


def require_reader(principal: Principal | None = Depends(current_principal)) -> Principal:
    if principal is None:
        raise AppError(401, "unauthorized", "Sign in to continue.")
    return principal


def _origin_allowed(request: Request, settings: Settings) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return True  # non-browser client; the CSRF token below is still required
    parts = urlsplit(origin)
    candidate = f"{parts.scheme}://{parts.netloc}".rstrip("/")
    host = request.headers.get("host", "")
    if parts.netloc and parts.netloc == host:
        return True
    return candidate in settings.extra_origins


def require_writer(
    request: Request,
    principal: Principal = Depends(require_reader),
    settings: Settings = Depends(settings_dep),
) -> Principal:
    if principal.read_only:
        raise AppError(403, "read_only", "This is a read-only public demo; changes are disabled on the server.")
    if not _origin_allowed(request, settings):
        raise AppError(403, "bad_origin", "Request origin is not allowed.")
    sent = request.headers.get("x-csrf-token") or ""
    if not principal.csrf_token or not hmac.compare_digest(sent.encode(), principal.csrf_token.encode()):
        raise AppError(403, "csrf_failed", "Missing or invalid CSRF token. Reload the page and try again.")
    return principal

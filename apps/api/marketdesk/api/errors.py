"""Predictable JSON error objects: {"error": {"code", "message", "details", "request_id"}}.

Every response carries an X-Request-ID header (set by the app middleware); error bodies repeat it so the owner can
quote it, and server-side log lines for failures include it. Logs never contain request bodies, credentials or
cookies.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, ProgrammingError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("marketdesk.api")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_body(code: str, message: str, details: Any = None, request_id: str | None = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message, "details": details}
    if request_id:
        body["request_id"] = request_id
    return {"error": body}


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _json_error(request: Request, status: int, code: str, message: str, details: Any = None, headers=None):
    rid = request_id_of(request)
    merged = dict(headers or {})
    if rid:
        merged["X-Request-ID"] = rid
    return JSONResponse(error_body(code, message, details, rid), status_code=status, headers=merged or None)


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return _json_error(request, exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        fields = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            fields.append({"field": ".".join(loc) or None, "message": err.get("msg", "Invalid value")})
        return _json_error(request, 422, "validation_error", "Some fields are invalid.", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _json_error(request, exc.status_code, code, message, headers=getattr(exc, "headers", None))

    @app.exception_handler(OperationalError)
    async def _db(request: Request, exc: OperationalError):
        log.error(
            "database unavailable request_id=%s %s %s: %s",
            request_id_of(request),
            request.method,
            request.url.path,
            type(exc.orig).__name__ if exc.orig else type(exc).__name__,
        )
        return _json_error(
            request,
            503,
            "database_unavailable",
            "The database is unavailable or not initialised. Check the server logs; restarting the "
            "service applies any pending migrations.",
        )

    @app.exception_handler(ProgrammingError)
    async def _db_schema(request: Request, exc: ProgrammingError):
        # PostgreSQL reports a missing table/column as ProgrammingError (SQLSTATE 42P01 / 42703).
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code in ("42P01", "42703"):
            log.error("database schema error request_id=%s: %s", request_id_of(request), code)
            return _json_error(
                request,
                503,
                "database_unavailable",
                "The database is not initialised. Restarting the service applies pending migrations.",
            )
        log.exception("database programming error request_id=%s sqlstate=%s", request_id_of(request), code)
        return _server_error(request)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception(
            "unhandled error request_id=%s %s %s: %s",
            request_id_of(request),
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return _server_error(request)


def _server_error(request: Request) -> JSONResponse:
    rid = request_id_of(request)
    message = "Unexpected server error."
    if rid:
        message += f" Reference: {rid}."
    return _json_error(request, 500, "internal_error", message)

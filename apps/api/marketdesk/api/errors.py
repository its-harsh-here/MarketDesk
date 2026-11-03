"""Predictable JSON error objects: {"error": {"code", "message", "details"}}."""

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


def error_body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


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
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            fields.append({"field": ".".join(loc) or None, "message": err.get("msg", "Invalid value")})
        return JSONResponse(
            error_body("validation_error", "Some fields are invalid.", {"fields": fields}), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            error_body(code, message), status_code=exc.status_code, headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(OperationalError)
    async def _db(_: Request, exc: OperationalError):
        log.error("database error: %s", type(exc.orig).__name__ if exc.orig else type(exc).__name__)
        return JSONResponse(
            error_body(
                "database_unavailable",
                "The database is unavailable or not initialised. Check the server logs; restarting the "
                "service applies any pending migrations.",
            ),
            status_code=503,
        )

    @app.exception_handler(ProgrammingError)
    async def _db_schema(_: Request, exc: ProgrammingError):
        # PostgreSQL reports a missing table/column as ProgrammingError (SQLSTATE 42P01 / 42703).
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code in ("42P01", "42703"):
            log.error("database schema error: %s", code)
            return JSONResponse(
                error_body(
                    "database_unavailable",
                    "The database is not initialised. Restarting the service applies pending migrations.",
                ),
                status_code=503,
            )
        log.exception("database programming error")
        return JSONResponse(error_body("internal_error", "Unexpected server error."), status_code=500)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):  # pragma: no cover - safety net
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(error_body("internal_error", "Unexpected server error."), status_code=500)

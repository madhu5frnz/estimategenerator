"""Structured API errors.

Every error leaves the API as::

    {"success": false, "error_code": "...", "message": "...", "details": {...},
     "request_id": "..."}

Stack traces are logged, never returned.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import current_request_id
from app.domain.quantity import CalculationError
from app.domain.units import UnitError


class AppError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_response(
    status_code: int, error_code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        "message": message,
        "request_id": current_request_id(),
    }
    if details:
        body["details"] = details
    return JSONResponse(status_code=status_code, content=body)


_HTTP_CODES = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_FILE_TYPE",
    429: "RATE_LIMITED",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.error_code, exc.message, exc.details)

    @app.exception_handler(CalculationError)
    async def _calc_error(_: Request, exc: CalculationError) -> JSONResponse:
        return error_response(400, exc.code, exc.message, exc.details)

    @app.exception_handler(UnitError)
    async def _unit_error(_: Request, exc: UnitError) -> JSONResponse:
        return error_response(400, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ()) if p != "body"),
                "message": err.get("msg", ""),
            }
            for err in exc.errors()
        ]
        return error_response(
            400, "VALIDATION_ERROR", "Some fields are missing or invalid.", {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(exc.status_code, code, message)

    # Unexpected exceptions are handled by RequestIdMiddleware so the response keeps its
    # request id; see app/core/request_id.py.

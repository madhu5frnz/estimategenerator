from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

import structlog
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_VALID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
HEADER = "x-request-id"
log = structlog.get_logger(__name__)

INTERNAL_ERROR_MESSAGE = (
    "Something went wrong on our side. Please try again; if it continues, contact support "
    "with the request id."
)


def current_request_id() -> str | None:
    return _request_id.get()


class RequestIdMiddleware:
    """Accepts a well-formed incoming X-Request-ID or generates one; echoes it back and
    binds it to every log line of the request.

    It is also the last line of defence: an unexpected exception is logged with its stack
    trace and turned into the standard error envelope, still carrying the request id.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _VALID.match(incoming) else uuid.uuid4().hex
        token = _request_id.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = False

        async def send_with_header(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                headers.append((HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        except Exception as exc:
            log.exception("unhandled_error", path=scope.get("path"), error_type=type(exc).__name__)
            if started:
                raise
            response = JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error_code": "INTERNAL_ERROR",
                    "message": INTERNAL_ERROR_MESSAGE,
                    "request_id": request_id,
                },
            )
            await response(scope, receive, send_with_header)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            _request_id.reset(token)

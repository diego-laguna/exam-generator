"""One error format for the whole API: RFC 9457 `application/problem+json`.

Routes and dependencies raise `exam_core.errors.DomainError` subclasses; the handlers here turn
them (and framework errors) into a `ProblemDetail`. Unexpected exceptions become a generic 500
whose text is only logged, never returned.
"""

import logging
import re
import time
import uuid
from http import HTTPStatus
from typing import Any

from exam_core.errors import DomainError, FieldError
from exam_core.logging import log_context
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)
access_log = logging.getLogger("app.access")

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_JOIN_PATH = re.compile(r"(/join/)[^/]+")
_LOC_PREFIXES = {"body", "query", "path", "header", "cookie"}

_GENERIC_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
}


class ProblemFieldError(BaseModel):
    field: str = Field(description="Dotted path of the invalid field, without body/query/path.")
    message: str
    type: str


class ProblemDetail(BaseModel):
    """Every error response (RFC 9457). Branch on `code`, show `detail`."""

    type: str = "about:blank"
    title: str = Field(description="HTTP reason phrase.")
    status: int
    code: str = Field(description="Stable machine-readable code, e.g. EXAM_WINDOW_CLOSED.")
    detail: str = Field(description="Human-readable message, safe to show.")
    instance: str = Field(description="Request path.")
    request_id: str = Field(description="Also in the X-Request-ID header; quote it when reporting a bug.")
    errors: list[ProblemFieldError] = []


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ProblemDetail, "description": "Client error"},
    "5XX": {"model": ProblemDetail, "description": "Server error"},
    422: {"model": ProblemDetail, "description": "Validation error"},
}


def _title(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def safe_path(path: str) -> str:
    """The path for logs: the join token in /join/{token} is a credential."""
    return _JOIN_PATH.sub(r"\1{token}", path)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or "unknown"


def problem_response(
    request: Request,
    status: int,
    code: str,
    detail: str,
    *,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        title=_title(status),
        status=status,
        code=code,
        detail=detail,
        instance=request.url.path,
        request_id=_request_id(request),
        errors=[ProblemFieldError(field=e.field, message=e.message, type=e.type) for e in errors or []],
    )
    return JSONResponse(
        body.model_dump(), status_code=status, headers=headers, media_type=PROBLEM_MEDIA_TYPE
    )


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return problem_response(
        request, exc.status, exc.code, exc.message, errors=exc.errors, headers=exc.headers
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _GENERIC_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) else _title(exc.status_code)
    return problem_response(
        request, exc.status_code, code, detail, headers=dict(exc.headers) if exc.headers else None
    )


def _field_errors(exc: RequestValidationError) -> list[FieldError]:
    out: list[FieldError] = []
    for err in exc.errors():
        loc = [str(p) for p in err["loc"]]
        if loc and loc[0] in _LOC_PREFIXES:
            loc = loc[1:]
        message = str(err["msg"]).removeprefix("Value error, ")
        out.append(FieldError(field=".".join(loc), message=message, type=str(err["type"])))
    return out


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return problem_response(
        request, 422, "VALIDATION_ERROR", "The request is not valid", errors=_field_errors(exc)
    )


def internal_error_response(request: Request, exc: BaseException) -> JSONResponse:
    log.error(
        "Unhandled exception on %s %s", request.method, safe_path(request.url.path), exc_info=exc
    )
    return problem_response(request, 500, "INTERNAL_ERROR", "Internal server error")


class RequestContextMiddleware:
    """Request id, access log and the 500 fallback.

    Pure ASGI and the innermost catch-all for unexpected errors: Starlette's own 500 handling sits
    outside user middleware, so doing it here keeps `X-Request-ID` on those responses too.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        with log_context(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception as exc:
                if response_started:
                    raise
                await internal_error_response(request, exc)(scope, receive, send_with_id)
            finally:
                access_log.info(
                    "%s %s -> %s",
                    request.method,
                    safe_path(request.url.path),
                    status_code,
                    extra={
                        "request_id": request_id,
                        "method": request.method,
                        "path": safe_path(request.url.path),
                        "status": status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )


def install_error_handling(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_middleware(RequestContextMiddleware)

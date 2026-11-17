"""Errors shared by the API and the worker. No web framework imports: the API maps `DomainError`
to an HTTP response (apps/api/app/errors.py)."""

from dataclasses import dataclass


class IngestionError(Exception):
    """A failure whose message is safe to show to users."""


@dataclass(frozen=True)
class FieldError:
    """One invalid input field: dotted path, human message and a machine type."""

    field: str
    message: str
    type: str = "value_error"


class DomainError(Exception):
    """An expected failure whose message is safe to show to the caller.

    Subclasses fix the HTTP `status` and a default `code`; pass `code=` for a specific one.
    """

    status: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        errors: list[FieldError] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.errors: list[FieldError] = errors or []
        self.headers: dict[str, str] = headers or {}


class BadRequest(DomainError):
    status = 400
    code = "BAD_REQUEST"


class Unauthenticated(DomainError):
    status = 401
    code = "UNAUTHENTICATED"


class PermissionDenied(DomainError):
    status = 403
    code = "FORBIDDEN"


class NotFound(DomainError):
    status = 404
    code = "NOT_FOUND"


class Conflict(DomainError):
    status = 409
    code = "CONFLICT"


class TooManyRequests(DomainError):
    status = 429
    code = "TOO_MANY_REQUESTS"


class PayloadTooLarge(DomainError):
    status = 413
    code = "PAYLOAD_TOO_LARGE"


class InvalidInput(DomainError):
    status = 422
    code = "VALIDATION_ERROR"


class NotImplementedYet(DomainError):
    status = 501
    code = "NOT_IMPLEMENTED"


class ServiceUnavailable(DomainError):
    status = 503
    code = "SERVICE_UNAVAILABLE"

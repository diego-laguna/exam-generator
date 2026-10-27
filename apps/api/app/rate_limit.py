"""Login rate limiting backed by Postgres (counters must be shared by all API tasks).

Only failed logins are stored. `check_login_allowed` is a dependency of the login route: it
counts failures in a sliding window per username and per client IP and raises 429 when either
reaches its limit. The answer is the same whether or not the username exists.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated

from exam_core.errors import TooManyRequests
from exam_core.models import LoginAttempt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, select

from app.clock import ClockDep
from app.config import get_settings
from app.dependencies import DbSession

_USERNAME_MAX = 255


@dataclass(frozen=True)
class LoginIdentity:
    username: str  # normalised: trimmed, lowercase
    ip: str


def client_ip(request: Request) -> str:
    """The proxy-appended X-Forwarded-For entry `trusted_proxy_hops` from the right, only when
    that setting is > 0 (a client can forge the left side); else the socket peer."""
    hops = get_settings().trusted_proxy_hops
    if hops > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops][:64]
    return (request.client.host if request.client else "unknown")[:64]


def _retry_after(times: list[datetime], limit: int, now: datetime, window: timedelta) -> int:
    """Seconds until enough failures expire for the count to drop below the limit.
    `times` is ascending."""
    expiring = times[len(times) - limit]
    return max(1, math.ceil((expiring + window - now).total_seconds()))


def check_login_allowed(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    clock: ClockDep,
) -> LoginIdentity:
    settings = get_settings()
    identity = LoginIdentity(form.username.strip().lower()[:_USERNAME_MAX], client_ip(request))
    now = clock()
    window = timedelta(seconds=settings.login_window_seconds)
    since = now - window
    waits: list[int] = []
    for column, value, limit in (
        (LoginAttempt.username, identity.username, settings.login_max_failures_per_username),
        (LoginAttempt.ip, identity.ip, settings.login_max_failures_per_ip),
    ):
        times = list(
            db.scalars(
                select(LoginAttempt.created_at)
                .where(column == value, LoginAttempt.created_at > since)
                .order_by(LoginAttempt.created_at)
            )
        )
        if len(times) >= limit:
            waits.append(_retry_after(times, limit, now, window))
    if waits:
        raise TooManyRequests(
            "Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(max(waits))},
        )
    return identity


def record_login_failure(db: DbSession, identity: LoginIdentity, now: datetime) -> None:
    """Adds a failure and purges rows older than the window. The caller commits."""
    window = timedelta(seconds=get_settings().login_window_seconds)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at <= now - window))
    db.add(LoginAttempt(username=identity.username, ip=identity.ip, created_at=now))


def clear_login_failures(db: DbSession, identity: LoginIdentity) -> None:
    """A successful login forgets that username's failures. The caller commits."""
    db.execute(delete(LoginAttempt).where(LoginAttempt.username == identity.username))

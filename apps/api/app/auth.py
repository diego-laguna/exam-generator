from datetime import UTC, datetime
from typing import Annotated

from exam_core.errors import Unauthenticated
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.clock import ClockDep
from app.errors import ProblemDetail
from app.dependencies import DbSession, get_current_claims
from app.rate_limit import (
    LoginIdentity,
    check_login_allowed,
    clear_login_failures,
    record_login_failure,
)
from exam_core.models import RefreshToken, RevokedToken, User
from app.security import (
    DUMMY_HASH,
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    password_hash,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


REFRESH_COOKIE = "refresh_token"
COOKIE_PATH = "/api/v1/auth"  # the browser sends it only to the auth endpoints


def _set_refresh_cookie(response: Response, raw: str) -> None:
    """Browser clients keep the refresh token in an httpOnly cookie, out of reach of page scripts.
    SameSite=Strict plus the narrow path keeps other sites from triggering a refresh or logout."""
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )


def _presented_refresh_token(request: Request, body: RefreshRequest | None) -> str | None:
    """The request body wins (API clients); browsers send the cookie."""
    return body.refresh_token if body is not None else request.cookies.get(REFRESH_COOKIE)


def _issue_tokens(db: Session, user: User) -> TokenPair:
    raw, hashed, expires_at = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=hashed, expires_at=expires_at))
    return TokenPair(access_token=create_access_token(user.id, user.role), refresh_token=raw)


def revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    """Ends every session of a user. Call this on password change."""
    db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))


def _invalid_credentials() -> Unauthenticated:
    return Unauthenticated(
        "Incorrect username or password",
        code="INVALID_CREDENTIALS",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Sign in",
    responses={429: {"model": ProblemDetail, "description": "Too many failed logins; see Retry-After"}},
    description=(
        "Exchange a username and password (OAuth2 password form) for a short-lived access token and a single-use refresh token. Browsers also receive the refresh token as an httpOnly cookie."
        "\n\n"
        "**Use case:** Dave opens the web app and signs in as `dave`. The app keeps the access token in memory and sends it as `Authorization: Bearer ...` on every call. In Swagger, use the Authorize button."
    ),
)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    response: Response,
    identity: Annotated[LoginIdentity, Depends(check_login_allowed)],
    clock: ClockDep,
):
    user = db.scalar(select(User).where(User.username == form.username))
    # Always run a hash verification so timing doesn't reveal valid usernames.
    password_ok = password_hash.verify(
        form.password, user.password_hash if user else DUMMY_HASH
    )
    if not (user and user.is_active and password_ok):
        record_login_failure(db, identity, clock())
        db.commit()
        raise _invalid_credentials()
    clear_login_failures(db, identity)
    db.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.expires_at < datetime.now(UTC)
        )
    )
    tokens = _issue_tokens(db, user)
    db.commit()
    _set_refresh_cookie(response, tokens.refresh_token)
    return tokens


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate the session tokens",
    description=(
        "Trade a refresh token (request body, or the cookie when the body is empty) for a new access token and a new refresh token. A refresh token works once; presenting it a second time fails."
        "\n\n"
        "**Use case:** Dave's access token expired after 15 minutes. The web app calls this endpoint silently and retries the request that got a 401, so Dave never sees the login screen."
    ),
)
def refresh(
    request: Request, response: Response, db: DbSession, body: RefreshRequest | None = None
):
    presented = _presented_refresh_token(request, body)
    # Single-use: the DELETE consumes the token atomically, so a replay finds nothing.
    row = (
        db.execute(
            delete(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(presented))
            .returning(RefreshToken.user_id, RefreshToken.expires_at)
        ).one_or_none()
        if presented
        else None
    )
    user = db.get(User, row.user_id) if row else None
    if not (row and row.expires_at > datetime.now(UTC) and user and user.is_active):
        db.commit()  # persist the deletion of an expired/consumed token
        raise Unauthenticated(
            "Invalid or expired refresh token",
            code="INVALID_REFRESH_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tokens = _issue_tokens(db, user)
    db.commit()
    _set_refresh_cookie(response, tokens.refresh_token)
    return tokens


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description=(
        "Revokes the current access token and deletes the presented refresh token (body or cookie), then clears the cookie. Requires a valid access token."
        "\n\n"
        "**Use case:** Dave signs out on a shared classroom computer. The old tokens stop working immediately, even if someone copied them."
    ),
)
def logout(
    request: Request,
    claims: Annotated[dict, Depends(get_current_claims)],
    db: DbSession,
    body: RefreshRequest | None = None,
):
    presented = _presented_refresh_token(request, body)
    if presented is not None:
        # Scoped to the caller so one user can't end another's session.
        db.execute(
            delete(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(presented),
                RefreshToken.user_id == int(claims["sub"]),
            )
        )
    # Revoke the access token too, so logout is immediate rather than ≤15 min later.
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(UTC)))
    db.execute(
        insert(RevokedToken)
        .values(jti=claims["jti"], expires_at=datetime.fromtimestamp(claims["exp"], UTC))
        .on_conflict_do_nothing()
    )
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response

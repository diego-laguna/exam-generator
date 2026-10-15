from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.dependencies import DbSession, get_current_claims
from app.models import RefreshToken, RevokedToken, User
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


def _issue_tokens(db: Session, user: User) -> TokenPair:
    raw, hashed, expires_at = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=hashed, expires_at=expires_at))
    return TokenPair(access_token=create_access_token(user.id, user.role), refresh_token=raw)


def revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    """Ends every session of a user. Call this on password change."""
    db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/login", response_model=TokenPair)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    user = db.scalar(select(User).where(User.username == form.username))
    # Always run a hash verification so timing doesn't reveal valid usernames.
    password_ok = password_hash.verify(
        form.password, user.password_hash if user else DUMMY_HASH
    )
    if not (user and user.is_active and password_ok):
        raise _invalid_credentials()
    db.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.expires_at < datetime.now(UTC)
        )
    )
    tokens = _issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: DbSession):
    # Single-use: the DELETE consumes the token atomically, so a replay finds nothing.
    row = db.execute(
        delete(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(body.refresh_token))
        .returning(RefreshToken.user_id, RefreshToken.expires_at)
    ).one_or_none()
    user = db.get(User, row.user_id) if row else None
    if not (row and row.expires_at > datetime.now(UTC) and user and user.is_active):
        db.commit()  # persist the deletion of an expired/consumed token
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tokens = _issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    claims: Annotated[dict, Depends(get_current_claims)],
    db: DbSession,
    body: RefreshRequest | None = None,
):
    if body is not None:
        # Scoped to the caller so one user can't end another's session.
        db.execute(
            delete(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(body.refresh_token),
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)

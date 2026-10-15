from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import RevokedToken, User
from app.security import (
    DUMMY_HASH,
    create_access_token,
    decode_access_token,
    password_hash,
)

router = APIRouter(tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

DbSession = Annotated[Session, Depends(get_db)]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def get_current_claims(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> dict:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_access_token(token)
    except jwt.InvalidTokenError:
        raise unauthorized
    if db.get(RevokedToken, claims["jti"]) is not None:
        raise unauthorized
    return claims


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    user = db.scalar(select(User).where(User.username == form.username))
    # Always run a hash verification so timing doesn't reveal valid usernames.
    password_ok = password_hash.verify(
        form.password, user.password_hash if user else DUMMY_HASH
    )
    if not (user and user.is_active and password_ok):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(str(user.id)))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(claims: Annotated[dict, Depends(get_current_claims)], db: DbSession):
    # Drop revocations for tokens that have already expired, then record this one.
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(UTC)))
    db.execute(
        insert(RevokedToken)
        .values(jti=claims["jti"], expires_at=datetime.fromtimestamp(claims["exp"], UTC))
        .on_conflict_do_nothing()
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

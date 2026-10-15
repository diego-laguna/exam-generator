from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import RevokedToken, Role, User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_claims(token: Annotated[str, Depends(oauth2_scheme)], db: DbSession) -> dict:
    try:
        claims = decode_access_token(token)
    except jwt.InvalidTokenError:
        raise _unauthorized()
    if db.get(RevokedToken, claims["jti"]) is not None:
        raise _unauthorized()
    return claims


def get_current_user(
    claims: Annotated[dict, Depends(get_current_claims)], db: DbSession
) -> User:
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: Role):
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker

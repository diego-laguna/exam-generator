from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.security import (
    DUMMY_HASH,
    create_access_token,
    decode_access_token,
    denylist,
    password_hash,
)

router = APIRouter(tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def get_current_claims(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_access_token(token)
    except jwt.InvalidTokenError:
        raise unauthorized
    if claims["jti"] in denylist:
        raise unauthorized
    return claims


@router.post("/login", response_model=Token)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    settings: Annotated[Settings, Depends(get_settings)],
):
    user_ok = form.username == settings.auth_username
    hash_to_check = settings.auth_password_hash if user_ok else DUMMY_HASH
    password_ok = password_hash.verify(form.password, hash_to_check)
    if not (user_ok and password_ok):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(form.username))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(claims: Annotated[dict, Depends(get_current_claims)]):
    denylist.add(claims["jti"], claims["exp"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)

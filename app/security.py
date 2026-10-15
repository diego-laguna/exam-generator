import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.config import get_settings

password_hash = PasswordHash.recommended()
# Verified against when the username is unknown, so timing doesn't reveal it.
DUMMY_HASH = password_hash.hash("dummy-password")


def create_access_token(subject: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "jti"]},
    )


class TokenDenylist:
    """In-memory revoked-token store (jti -> exp). Resets on restart and is
    per-process; swap for Redis/DB if running multiple workers."""

    def __init__(self) -> None:
        self._revoked: dict[str, float] = {}

    def add(self, jti: str, exp: float) -> None:
        self._purge()
        self._revoked[jti] = exp

    def __contains__(self, jti: str) -> bool:
        self._purge()
        return jti in self._revoked

    def _purge(self) -> None:
        now = time.time()
        self._revoked = {j: e for j, e in self._revoked.items() if e > now}


denylist = TokenDenylist()

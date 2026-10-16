from datetime import UTC, datetime

import jwt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.auth import revoke_all_refresh_tokens
from app.config import get_settings
from app.db import SessionLocal
from app.dependencies import require_role
from app.main import app
from app.models import RefreshToken, Role, User

# Test-only routes to exercise the authorization dependencies.
app.get("/_test/admin", dependencies=[Depends(require_role(Role.admin))])(lambda: {"ok": True})
app.get("/_test/student", dependencies=[Depends(require_role(Role.student))])(lambda: {"ok": True})

client = TestClient(app)


def login(password="wonderland", username="alice"):
    return client.post("/api/v1/auth/login", data={"username": username, "password": password})


def tokens(**kw):
    r = login(**kw)
    assert r.status_code == 200
    return r.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def logout(t, refresh=None):
    body = {"refresh_token": refresh} if refresh else None
    return client.post("/api/v1/auth/logout", headers=bearer(t), json=body)


def refresh(raw):
    return client.post("/api/v1/auth/refresh", json={"refresh_token": raw})


def test_login_success():
    body = login().json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


def test_login_wrong_password():
    assert login(password="nope").status_code == 401


def test_login_unknown_user():
    assert login(username="nobody").status_code == 401


def test_login_inactive_user():
    def set_active(value):
        with SessionLocal() as db:
            db.execute(update(User).where(User.username == "carol").values(is_active=value))
            db.commit()

    set_active(False)
    try:
        assert login(username="carol", password="christmas").status_code == 401
    finally:
        set_active(True)


def test_access_token_claims_and_lifetime():
    claims = jwt.decode(
        tokens()["access_token"], options={"verify_signature": False}
    )
    assert claims["role"] == "admin"
    assert claims["exp"] - claims["iat"] == get_settings().access_token_expire_minutes * 60
    assert get_settings().access_token_expire_minutes == 15


def test_refresh_rotates_token():
    first = tokens()
    r = refresh(first["refresh_token"])
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    # The consumed token can't be replayed (FR-AUTH-3).
    assert refresh(first["refresh_token"]).status_code == 401
    # The rotated one still works.
    assert refresh(second["refresh_token"]).status_code == 200


def test_refresh_rejects_garbage():
    assert refresh("garbage").status_code == 401


def test_refresh_rejects_expired():
    t = tokens()
    with SessionLocal() as db:
        db.execute(update(RefreshToken).values(expires_at=RefreshToken.created_at))
        db.commit()
    assert refresh(t["refresh_token"]).status_code == 401


def test_logout_requires_token():
    assert client.post("/api/v1/auth/logout").status_code == 401


def test_logout_rejects_garbage_token():
    assert logout("garbage").status_code == 401


def test_logout_revokes_access_and_refresh_tokens():
    t = tokens()
    assert logout(t["access_token"], t["refresh_token"]).status_code == 204
    # Access token is dead immediately, refresh token is gone.
    assert logout(t["access_token"]).status_code == 401
    assert refresh(t["refresh_token"]).status_code == 401


def test_logout_cannot_delete_other_users_refresh_token():
    alice, bob = tokens(), tokens(username="bob", password="builder")
    assert logout(bob["access_token"], alice["refresh_token"]).status_code == 204
    assert refresh(alice["refresh_token"]).status_code == 200


def test_revoke_all_refresh_tokens():
    t1, t2 = tokens(), tokens()
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == "alice"))
        revoke_all_refresh_tokens(db, uid)
        db.commit()
    assert refresh(t1["refresh_token"]).status_code == 401
    assert refresh(t2["refresh_token"]).status_code == 401


@pytest.mark.parametrize(
    "creds,path,status",
    [
        (("alice", "wonderland"), "/_test/admin", 200),
        (("bob", "builder"), "/_test/admin", 403),
        (("bob", "builder"), "/_test/student", 200),
        (("alice", "wonderland"), "/_test/student", 403),
    ],
)
def test_require_role(creds, path, status):
    t = tokens(username=creds[0], password=creds[1])
    assert client.get(path, headers=bearer(t["access_token"])).status_code == status


def test_old_unversioned_routes_are_gone():
    assert client.post("/login").status_code == 404


def test_expired_access_token_rejected():
    # FR-AUTH-2: an expired token gets 401 on protected endpoints.
    s = get_settings()
    now = int(datetime.now(UTC).timestamp())
    expired = jwt.encode(
        {"sub": "1", "role": "admin", "iat": now - 120, "exp": now - 60, "jti": "expired-jti"},
        s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
    )
    assert client.get("/_test/admin", headers=bearer(expired)).status_code == 401

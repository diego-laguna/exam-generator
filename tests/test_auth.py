from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def login(password="wonderland", username="alice"):
    return client.post("/login", data={"username": username, "password": password})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_success():
    r = login()
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password():
    assert login(password="nope").status_code == 401


def test_login_unknown_user():
    assert login(username="bob").status_code == 401


def test_logout_requires_token():
    assert client.post("/logout").status_code == 401


def test_logout_rejects_garbage_token():
    assert client.post("/logout", headers=auth("garbage")).status_code == 401


def test_login_inactive_user():
    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        db.execute(update(User).where(User.username == "carol").values(is_active=False))
        db.commit()
    try:
        assert login(username="carol", password="christmas").status_code == 401
    finally:
        with SessionLocal() as db:
            db.execute(update(User).where(User.username == "carol").values(is_active=True))
            db.commit()


def test_logout_revokes_token():
    token = login().json()["access_token"]
    assert client.post("/logout", headers=auth(token)).status_code == 204
    # Same token can no longer be used.
    assert client.post("/logout", headers=auth(token)).status_code == 401

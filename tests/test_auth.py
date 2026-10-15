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


def test_logout_revokes_token():
    token = login().json()["access_token"]
    assert client.post("/logout", headers=auth(token)).status_code == 204
    # Same token can no longer be used.
    assert client.post("/logout", headers=auth(token)).status_code == 401

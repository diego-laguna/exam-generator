import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
URL = "/api/v1/users"


def token(username, password):
    r = client.post("/api/v1/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def admin():
    return token("alice", "wonderland")


def new_name():
    return f"user-{uuid.uuid4().hex[:8]}"


def test_admin_creates_user_who_can_log_in():
    name = new_name()
    r = client.post(URL, headers=admin(), json={"username": name, "password": "s3cret-pass"})
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == name
    assert body["role"] == "student"
    assert body["is_active"] is True
    assert "password" not in body and "password_hash" not in body
    login = client.post("/api/v1/auth/login", data={"username": name, "password": "s3cret-pass"})
    assert login.status_code == 200


def test_admin_can_create_admin():
    r = client.post(
        URL,
        headers=admin(),
        json={"username": new_name(), "password": "s3cret-pass", "role": "admin"},
    )
    assert r.status_code == 201
    assert r.json()["role"] == "admin"


def test_student_forbidden():
    r = client.post(
        URL,
        headers=token("bob", "builder"),
        json={"username": new_name(), "password": "s3cret-pass"},
    )
    assert r.status_code == 403


def test_requires_authentication():
    r = client.post(URL, json={"username": new_name(), "password": "s3cret-pass"})
    assert r.status_code == 401


def test_duplicate_username_conflicts():
    r = client.post(URL, headers=admin(), json={"username": "bob", "password": "s3cret-pass"})
    assert r.status_code == 409


def test_validation():
    h = admin()
    for payload in [
        {"username": new_name(), "password": "short"},
        {"username": "ab", "password": "s3cret-pass"},
        {"username": "bad name!", "password": "s3cret-pass"},
        {"username": new_name(), "password": "s3cret-pass", "role": "root"},
    ]:
        assert client.post(URL, headers=h, json=payload).status_code == 422

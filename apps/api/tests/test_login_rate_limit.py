from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.clock import get_clock
from app.config import get_settings
from app.main import app
from exam_core.db import SessionLocal
from exam_core.models import LoginAttempt

client = TestClient(app)
T0 = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)


class Now:
    def __init__(self) -> None:
        self.t = T0


@pytest.fixture(autouse=True)
def clock():
    with SessionLocal() as db:
        db.execute(delete(LoginAttempt))
        db.commit()
    now = Now()
    app.dependency_overrides[get_clock] = lambda: lambda: now.t
    yield now
    app.dependency_overrides.pop(get_clock, None)
    with SessionLocal() as db:
        db.execute(delete(LoginAttempt))
        db.commit()


def login(username="alice", password="nope", headers=None):
    return client.post(
        "/api/v1/auth/login", data={"username": username, "password": password}, headers=headers
    )


def count() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(LoginAttempt)) or 0


def test_below_limit_is_401_then_429_with_retry_after():
    for _ in range(5):
        assert login().status_code == 401
    r = login()
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "TOO_MANY_REQUESTS"
    assert r.headers["retry-after"] == "900"
    # even the right password is refused while locked
    assert login(password="wonderland").status_code == 429


def test_unknown_user_looks_the_same():
    for _ in range(5):
        assert login(username="ghost").status_code == 401
    r = login(username="ghost")
    assert r.status_code == 429


def test_username_is_normalised():
    for name in ["Alice", "ALICE", " alice", "alice", "aLiCe"]:
        assert login(username=name).status_code == 401
    assert login(username="alice").status_code == 429


def test_ip_limit_across_usernames(monkeypatch):
    monkeypatch.setattr(get_settings(), "login_max_failures_per_ip", 4)
    for i in range(4):
        assert login(username=f"user{i}").status_code == 401
    assert login(username="another").status_code == 429


def test_success_clears_username_failures():
    for _ in range(4):
        assert login().status_code == 401
    assert login(password="wonderland").status_code == 200
    assert count() == 0
    for _ in range(5):
        assert login().status_code == 401


def test_window_expiry_and_retry_after(clock):
    for _ in range(5):
        login()
    clock.t = T0 + timedelta(seconds=600)
    r = login()
    assert r.status_code == 429
    assert r.headers["retry-after"] == "300"
    clock.t = T0 + timedelta(seconds=901)
    assert login().status_code == 401
    assert count() == 1  # old rows purged on the new failure


def test_forwarded_for_ignored_when_hops_zero(monkeypatch):
    monkeypatch.setattr(get_settings(), "login_max_failures_per_ip", 3)
    for i in range(3):
        assert login(username=f"u{i}", headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code == 401
    assert login(username="x", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 429


def test_forwarded_for_honoured_when_hops_set(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 3)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    for i in range(3):
        # the left side is attacker-controlled; the ALB-appended right entry counts
        h = {"X-Forwarded-For": f"spoof{i}, 8.8.8.8"}
        assert login(username=f"u{i}", headers=h).status_code == 401
    assert login(username="x", headers={"X-Forwarded-For": "1, 8.8.8.8"}).status_code == 429
    assert login(username="x", headers={"X-Forwarded-For": "1, 7.7.7.7"}).status_code == 401

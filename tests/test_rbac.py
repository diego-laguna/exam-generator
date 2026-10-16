"""Role-based access matrix for every endpoint except /auth/* and /health.

Allowed roles reach the 501 stub; other roles get 403; anonymous callers get 401.
Authorization must run before anything else, so these hold regardless of the stub.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
P = "/api/v1"

ADMIN, STUDENT = "admin", "student"
ANY = {ADMIN, STUDENT}

# (method, path, roles allowed)
ENDPOINTS = [
    ("POST", "/users", {ADMIN}),
    ("POST", "/sources", {ADMIN}),
    ("GET", "/sources", ANY),
    ("DELETE", "/sources/1", {ADMIN}),
    ("POST", "/samples", {ADMIN}),
    ("POST", "/exams", {STUDENT}),
    ("GET", "/exams/1", {STUDENT}),
    ("POST", "/exams/1/start", {STUDENT}),
    ("PUT", "/exams/1/answers/1", {STUDENT}),
    ("POST", "/exams/1/submit", {STUDENT}),
    ("GET", "/exams/1/results", {STUDENT}),
    ("GET", "/me/stats", ANY),
]

USERS = {ADMIN: ("alice", "wonderland"), STUDENT: ("bob", "builder")}


def headers_for(role):
    username, password = USERS[role]
    r = client.post(f"{P}/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("method,path,allowed", ENDPOINTS)
def test_anonymous_gets_401(method, path, allowed):
    assert client.request(method, P + path).status_code == 401


@pytest.mark.parametrize("method,path,allowed", ENDPOINTS)
@pytest.mark.parametrize("role", [ADMIN, STUDENT])
def test_role_access(method, path, allowed, role):
    r = client.request(method, P + path, headers=headers_for(role))
    if role in allowed:
        # Passed authorization. 501 for stubs; POST /users is real, so it answers 422 (no body).
        assert r.status_code in (501, 422), r.text
    else:
        assert r.status_code == 403, r.text


def test_public_endpoints_need_no_token():
    assert client.get("/health").status_code == 200
    assert client.post(f"{P}/auth/login", data={"username": "x", "password": "y"}).status_code == 401


def test_all_v1_routes_are_covered_by_the_matrix():
    """Fails when a new endpoint is added without an entry in ENDPOINTS."""
    covered = {(m, P + p) for m, p, _ in ENDPOINTS}
    public = {"/health", f"{P}/auth/login", f"{P}/auth/refresh"}
    routes = set()
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith(P) or path == "/health":
            for m in getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}:
                routes.add((m, path))
    import re

    def normalize(path):
        return re.sub(r"\{[^}]+\}", "1", path)

    uncovered = {
        (m, p) for m, p in routes
        if p not in public and f"{P}/auth/logout" != p and (m, normalize(p)) not in covered
    }
    assert not uncovered, f"Endpoints missing from the RBAC matrix: {sorted(uncovered)}"

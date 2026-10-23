import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import install_error_handling
from app.main import app
from exam_core.errors import Conflict

# Test-only routes live on their own app so the real route table stays clean.
probe = FastAPI()
install_error_handling(probe)


def _boom() -> None:
    raise RuntimeError("secret internal detail")


def _conflict() -> None:
    raise Conflict("Already there", code="SOMETHING_DUPLICATE")


probe.get("/_test/boom")(_boom)
probe.get("/_test/conflict")(_conflict)


@probe.get("/_test/validate")
def _validate(n: int) -> dict[str, int]:
    return {"n": n}


client = TestClient(app)
probe_client = TestClient(probe)
PROBLEM = "application/problem+json"


def test_domain_error_is_a_problem():
    r = probe_client.get("/_test/conflict")
    assert r.status_code == 409
    assert r.headers["content-type"].startswith(PROBLEM)
    body = r.json()
    assert body["code"] == "SOMETHING_DUPLICATE"
    assert body["detail"] == "Already there"
    assert body["title"] == "Conflict"
    assert body["status"] == 409
    assert body["type"] == "about:blank"
    assert body["instance"] == "/_test/conflict"
    assert body["request_id"] == r.headers["x-request-id"]
    assert body["errors"] == []


def test_unknown_route_is_404_problem():
    r = client.get("/nope")
    assert r.status_code == 404 and r.headers["content-type"].startswith(PROBLEM)
    assert r.json()["code"] == "NOT_FOUND"


def test_wrong_method_is_405_problem():
    r = client.post("/health")
    assert r.status_code == 405 and r.headers["content-type"].startswith(PROBLEM)
    assert r.json()["code"] == "METHOD_NOT_ALLOWED"
    assert "allow" in r.headers


def test_validation_error_lists_fields():
    r = probe_client.get("/_test/validate", params={"n": "x"})
    assert r.status_code == 422 and r.headers["content-type"].startswith(PROBLEM)
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["field"] == "n"
    assert body["errors"][0]["type"]


def test_body_validation_strips_prefix_and_value_error():
    admin = client.post("/api/v1/auth/login", data={"username": "alice", "password": "wonderland"}).json()
    h = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post("/api/v1/users", headers=h, json={"username": "x", "password": "short", "role": "teacher"})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["errors"]}
    assert fields and not any(f.startswith("body") for f in fields)
    assert not any(e["message"].startswith("Value error") for e in r.json()["errors"])


def test_missing_token_is_401_with_challenge():
    r = client.get("/api/v1/documents")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["code"] == "UNAUTHENTICATED"


def test_bad_token_is_401_invalid_token():
    r = client.get("/api/v1/documents", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_TOKEN"
    assert r.headers["www-authenticate"] == "Bearer"


def test_unhandled_exception_is_generic_500(caplog):
    with caplog.at_level(logging.ERROR):
        r = probe_client.get("/_test/boom", headers={"X-Request-ID": "req-500"})
    assert r.status_code == 500
    assert r.headers["content-type"].startswith(PROBLEM)
    assert r.headers["x-request-id"] == "req-500"
    body = r.json()
    assert body["code"] == "INTERNAL_ERROR" and body["detail"] == "Internal server error"
    assert body["request_id"] == "req-500"
    assert "secret internal detail" not in r.text
    assert any(rec.exc_info and "secret internal detail" in str(rec.exc_info[1]) for rec in caplog.records)


def test_request_id_is_echoed():
    r = client.get("/health", headers={"X-Request-ID": "abc-123.x"})
    assert r.headers["x-request-id"] == "abc-123.x"


def test_request_id_is_generated():
    r = client.get("/health")
    assert len(r.headers["x-request-id"]) == 32


def test_invalid_request_id_is_replaced():
    for bad in ("has space", "x" * 129, "a/b"):
        r = client.get("/health", headers={"X-Request-ID": bad})
        assert r.headers["x-request-id"] != bad and len(r.headers["x-request-id"]) == 32


def test_access_log_has_request_id(caplog):
    with caplog.at_level(logging.INFO, logger="app.access"):
        client.get("/health?token=secret", headers={"X-Request-ID": "log-me"})
    rec = next(r for r in caplog.records if r.name == "app.access")
    assert getattr(rec, "request_id") == "log-me"
    assert getattr(rec, "path") == "/health" and getattr(rec, "status") == 200
    assert "secret" not in rec.getMessage()
    assert isinstance(getattr(rec, "duration_ms"), float)


def test_openapi_documents_problem_detail():
    schema = client.get("/openapi.json").json()
    assert "ProblemDetail" in schema["components"]["schemas"]
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    op = schema["paths"]["/api/v1/documents"]["get"]["responses"]
    assert "application/problem+json" in op["404" if "404" in op else "4XX"]["content"]


def test_access_log_hides_the_join_token(caplog):
    with caplog.at_level(logging.INFO, logger="app.access"):
        client.get("/api/v1/join/SECRET-JOIN-TOKEN")
    rec = next(r for r in caplog.records if r.name == "app.access")
    assert "SECRET-JOIN-TOKEN" not in rec.getMessage()
    assert getattr(rec, "path") == "/api/v1/join/{token}"

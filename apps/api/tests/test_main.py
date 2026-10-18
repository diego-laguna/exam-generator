from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_also_reachable_under_the_api_prefix():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_blank_anthropic_key_counts_as_unset(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    assert Settings().anthropic_api_key is None  # pyright: ignore[reportCallIssue]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    key = Settings().anthropic_api_key  # pyright: ignore[reportCallIssue]
    assert key is not None and key.get_secret_value() == "sk-test"
    assert "sk-test" not in repr(key)


def test_database_url_is_built_from_parts_with_escaping(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("DB_HOST", "db.example.internal")
    monkeypatch.setenv("DB_USER", "learn")
    monkeypatch.setenv("DB_PASSWORD", "p@ss/w:rd%")
    url = Settings().sqlalchemy_url  # pyright: ignore[reportCallIssue]
    assert url == "postgresql+psycopg://learn:p%40ss%2Fw%3Ard%25@db.example.internal:5432/learn_assistant"

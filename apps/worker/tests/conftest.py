import os

import pytest

TEST_DB = "learn_assistant_worker_test"

# Must be set before exam_core is imported anywhere.
os.environ["DATABASE_URL"] = f"postgresql+psycopg://learn:learn@localhost:5432/{TEST_DB}"


@pytest.fixture(scope="session", autouse=True)
def _database():
    from exam_core.db import engine
    from exam_core.testing import bootstrap_database

    bootstrap_database(TEST_DB)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """A developer's real ANTHROPIC_API_KEY in .env must never be used by tests."""
    from worker import llm

    monkeypatch.setattr(llm, "_anthropic_llm", lambda: None)

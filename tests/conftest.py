import os

import psycopg
import pytest
from sqlalchemy import text

TEST_DB = "learn_assistant_test"
ADMIN_URL = "postgresql://learn:learn@localhost:5432/learn_assistant"

# Must be set before `app` is imported anywhere.
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["DATABASE_URL"] = f"postgresql+psycopg://learn:learn@localhost:5432/{TEST_DB}"


@pytest.fixture(scope="session", autouse=True)
def _database():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.execute(f"CREATE DATABASE {TEST_DB}")

    from app.db import Base, engine
    from app import models  # noqa: F401
    from scripts.seed import seed

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    seed()
    yield
    engine.dispose()

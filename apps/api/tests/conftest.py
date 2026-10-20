import os

import pytest

TEST_DB = "learn_assistant_test"

# Must be set before `app` is imported anywhere.
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["DATABASE_URL"] = f"postgresql+psycopg://learn:learn@localhost:5432/{TEST_DB}"


@pytest.fixture(scope="session", autouse=True)
def _database():
    from exam_core.db import engine
    from exam_core.testing import bootstrap_database
    from scripts.seed import seed
    from scripts.seed_reference import seed_reference

    bootstrap_database(TEST_DB)
    seed()
    seed_reference()
    yield
    engine.dispose()


@pytest.fixture
def queue():
    """Replaces SQS: records the messages the API sends. The worker has its own tests."""
    from app.main import app
    from app.queueing import get_queue
    from exam_core.testing import MemoryQueue

    fake = MemoryQueue()
    app.dependency_overrides[get_queue] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_queue, None)


@pytest.fixture
def storage():
    from app.main import app
    from exam_core.storage import get_storage
    from exam_core.testing import MemoryStorage

    fake = MemoryStorage()
    app.dependency_overrides[get_storage] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_storage, None)

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.embeddings import get_embedder
from app.fetching import IngestionError, get_fetcher
from app.main import app
from app.models import Chunk, SampleQuestion, Source, SourceStatus
from app.retrieval import similar_chunks
from tests.helpers_ingestion import FakeEmbedder, FakeFetcher, page

P = "/api/v1"
client = TestClient(app)
embedder = FakeEmbedder()

S3_TEXT = (
    "Amazon S3 is object storage built to store and retrieve any amount of data. "
    "Objects live in buckets and S3 offers eleven nines of durability across storage classes. "
)
VPC_TEXT = (
    "A VPC endpoint lets private subnets reach AWS services without an internet gateway. "
    "Gateway endpoints support S3 and DynamoDB while interface endpoints use PrivateLink. "
)


def _login(username, password):
    r = client.post(f"{P}/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin():
    return _login("alice", "wonderland")


@pytest.fixture
def student():
    return _login("bob", "builder")


@pytest.fixture
def fetcher():
    fake = FakeFetcher()
    app.dependency_overrides[get_fetcher] = lambda: fake
    app.dependency_overrides[get_embedder] = lambda: embedder
    yield fake
    app.dependency_overrides.pop(get_fetcher, None)
    app.dependency_overrides.pop(get_embedder, None)


def new_url():
    return f"https://docs.aws.amazon.com/test/{uuid.uuid4().hex}"


def add(admin, fetcher, content=None, url=None):
    url = url or new_url()
    if content is not None:
        fetcher.pages[url] = content
    r = client.post(f"{P}/sources", headers=admin, json={"url": url})
    return url, r


def get_source(headers, url):
    return next(s for s in client.get(f"{P}/sources", headers=headers).json() if s["url"] == url)


# --- creating sources -----------------------------------------------------------------------

def test_rejects_non_allowlisted_url(admin, fetcher):
    """FR-INGEST-1"""
    for url in ["https://evil.com/x", "http://docs.aws.amazon.com/x", "not a url"]:
        r = client.post(f"{P}/sources", headers=admin, json={"url": url})
        assert r.status_code == 422
    assert fetcher.calls == []


def test_ingestion_runs_and_source_becomes_ready(admin, fetcher):
    url, r = add(admin, fetcher, page("S3 Guide", ("Storage", S3_TEXT * 4), ("Security", S3_TEXT)))
    assert r.status_code == 202
    assert r.json()["status"] == "pending"
    src = get_source(admin, url)
    assert src["status"] == "ready"
    assert src["title"] == "S3 Guide"
    assert src["chunk_count"] >= 2
    assert src["error"] is None
    assert fetcher.calls == [url]


def test_chunks_store_heading_and_embedding(admin, fetcher):
    url, _ = add(admin, fetcher, page("T", ("Durability", S3_TEXT * 2)))
    with SessionLocal() as db:
        chunk = db.scalars(select(Chunk).join(Source).where(Source.url == url)).first()
        assert chunk is not None
        assert chunk.meta == {"heading": "Durability"}
        assert len(chunk.embedding) == 384
        assert chunk.content.startswith("Durability")


def test_duplicate_url_conflicts(admin, fetcher):
    url, _ = add(admin, fetcher, page("T", ("H", S3_TEXT * 2)))
    r = client.post(f"{P}/sources", headers=admin, json={"url": url})
    assert r.status_code == 409


def test_failed_fetch_marks_source_failed(admin, fetcher):
    url, r = add(admin, fetcher, IngestionError("The page returned HTTP 404"))
    assert r.status_code == 202
    src = get_source(admin, url)
    assert src["status"] == "failed"
    assert src["error"] == "The page returned HTTP 404"
    assert src["chunk_count"] == 0


def test_unexpected_error_does_not_leak_details(admin, fetcher):
    url, _ = add(admin, fetcher, RuntimeError("secret internal detail"))
    src = get_source(admin, url)
    assert src["status"] == "failed"
    assert "secret" not in src["error"]


def test_empty_page_fails(admin, fetcher):
    url, _ = add(admin, fetcher, "<html><body><p>hi</p></body></html>")
    src = get_source(admin, url)
    assert src["status"] == "failed" and "No readable content" in src["error"]


def test_students_do_not_see_error_details(admin, student, fetcher):
    url, _ = add(admin, fetcher, IngestionError("The page returned HTTP 500"))
    assert get_source(student, url)["status"] == "failed"
    assert get_source(student, url)["error"] is None


# --- access ---------------------------------------------------------------------------------

def test_student_can_list_but_not_modify(admin, student, fetcher):
    url, _ = add(admin, fetcher, page("T", ("H", S3_TEXT * 2)))
    assert client.get(f"{P}/sources", headers=student).status_code == 200
    assert client.post(f"{P}/sources", headers=student, json={"url": new_url()}).status_code == 403
    sid = get_source(admin, url)["id"]
    assert client.delete(f"{P}/sources/{sid}", headers=student).status_code == 403
    assert client.post(f"{P}/samples", headers=student, json={"samples": []}).status_code == 403


# --- delete ---------------------------------------------------------------------------------

def test_delete_removes_source_and_chunks(admin, fetcher):
    url, _ = add(admin, fetcher, page("T", ("H", S3_TEXT * 6)))
    src = get_source(admin, url)
    assert src["chunk_count"] > 0
    assert client.delete(f"{P}/sources/{src['id']}", headers=admin).status_code == 204
    with SessionLocal() as db:
        left = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.source_id == src["id"]))
    assert left == 0
    assert all(s["url"] != url for s in client.get(f"{P}/sources", headers=admin).json())


def test_delete_unknown_source_404(admin):
    assert client.delete(f"{P}/sources/999999", headers=admin).status_code == 404


def test_source_deleted_during_ingestion_is_handled(fetcher):
    """The job must not crash if the row disappears while it works."""
    from app.ingestion import ingest_source

    with SessionLocal() as db:
        src = Source(url=new_url(), status=SourceStatus.pending)
        db.add(src)
        db.commit()
        sid = src.id

    class DeletingFetcher:
        def __call__(self, url):
            with SessionLocal() as other:
                other.delete(other.get(Source, sid))
                other.commit()
            return page("T", ("H", S3_TEXT * 2))

    ingest_source(sid, DeletingFetcher(), embedder)
    with SessionLocal() as db:
        assert db.get(Source, sid) is None
        assert db.scalar(select(func.count()).select_from(Chunk).where(Chunk.source_id == sid)) == 0


# --- retrieval (pgvector) -------------------------------------------------------------------

def test_similarity_search_ranks_relevant_chunk_first(admin, fetcher):
    s3_url, _ = add(admin, fetcher, page("S3", ("Durability", S3_TEXT * 2)))
    vpc_url, _ = add(admin, fetcher, page("VPC", ("Endpoints", VPC_TEXT * 2)))
    ids = [get_source(admin, s3_url)["id"], get_source(admin, vpc_url)["id"]]
    with SessionLocal() as db:
        top = similar_chunks(db, embedder.embed(["gateway endpoints for private subnets"])[0], 2, ids)
        assert top[0].source_id == ids[1]
        top = similar_chunks(db, embedder.embed(["S3 buckets durability objects"])[0], 2, ids)
        assert top[0].source_id == ids[0]
        only_vpc = similar_chunks(db, embedder.embed(["S3 buckets"])[0], 5, [ids[1]])
        assert {c.source_id for c in only_vpc} == {ids[1]}


# --- samples --------------------------------------------------------------------------------

def sample(**over):
    base = {
        "task_statement": "1.1",
        "stem": "Which service provides temporary credentials to an EC2 instance?",
        "options": {"A": "IAM role", "B": "Root keys", "C": "Public bucket", "D": "Telnet"},
        "correct_option": "A",
    }
    return {**base, **over}


def post_samples(admin, *samples):
    return client.post(f"{P}/samples", headers=admin, json={"samples": list(samples)})


def test_create_samples(admin, fetcher):
    r = post_samples(admin, sample(), sample(task_statement=None, domain_id=4))
    assert r.status_code == 201
    body = r.json()
    assert body["created"] == 2 and len(body["ids"]) == 2
    with SessionLocal() as db:
        first, second = (db.get(SampleQuestion, i) for i in body["ids"])
        assert first is not None and second is not None
        assert first.domain_id == 1 and first.task_statement_id is not None
        assert second.domain_id == 4 and second.task_statement_id is None
        assert len(first.embedding) == 384


@pytest.mark.parametrize(
    "bad",
    [
        sample(task_statement="9.9"),
        sample(task_statement=None),  # no target
        sample(domain_id=2),  # task 1.1 belongs to domain 1
        sample(task_statement=None, domain_id=9),
        sample(options={"A": "x", "B": "y", "C": "z"}),
        sample(options={"A": "x", "B": "y", "C": "z", "E": "w"}),
        sample(correct_option="E"),
        sample(stem="short"),
    ],
)
def test_invalid_samples_rejected(admin, fetcher, bad):
    assert post_samples(admin, bad).status_code == 422


def test_empty_samples_rejected(admin, fetcher):
    assert client.post(f"{P}/samples", headers=admin, json={"samples": []}).status_code == 422


def test_batch_is_all_or_nothing(admin, fetcher):
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(SampleQuestion))
    assert post_samples(admin, sample(), sample(task_statement="9.9")).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SampleQuestion)) == before

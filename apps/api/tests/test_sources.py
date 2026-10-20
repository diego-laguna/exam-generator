import uuid

import pytest
from sqlalchemy import func, select

from app.retrieval import similar_chunks
from exam_core.db import SessionLocal
from exam_core.models import Chunk, SampleQuestion, Source, SourceStatus
from exam_core.queue import EmbedSamples, IngestSource
from exam_core.testing import FakeEmbedder
from tests.helpers_api import P, client, login

embedder = FakeEmbedder()

S3_TEXT = (
    "Amazon S3 is object storage built to store and retrieve any amount of data. "
    "Objects live in buckets and S3 offers eleven nines of durability across storage classes. "
)
VPC_TEXT = (
    "A VPC endpoint lets private subnets reach AWS services without an internet gateway. "
    "Gateway endpoints support S3 and DynamoDB while interface endpoints use PrivateLink. "
)


@pytest.fixture
def admin():
    return login("alice", "wonderland")


@pytest.fixture
def student():
    return login("bob", "builder")


def new_url():
    return f"https://docs.aws.amazon.com/test/{uuid.uuid4().hex}"


def add(admin, url=None):
    url = url or new_url()
    return url, client.post(f"{P}/sources", headers=admin, json={"url": url})


def get_source(headers, url):
    return next(s for s in client.get(f"{P}/sources", headers=headers).json() if s["url"] == url)


def add_ready_source(title, text):
    """A source as the worker leaves it: ready, with one embedded chunk."""
    with SessionLocal() as db:
        src = Source(url=new_url(), title=title, status=SourceStatus.ready)
        db.add(src)
        db.flush()
        db.add(Chunk(source_id=src.id, position=0, content=text, embedding=embedder.embed([text])[0], meta={"heading": title}))
        db.commit()
        return src.id


# --- creating sources -----------------------------------------------------------------------

def test_rejects_non_allowlisted_url(admin, queue):
    """FR-INGEST-1"""
    for url in ["https://evil.com/x", "http://docs.aws.amazon.com/x", "not a url"]:
        r = client.post(f"{P}/sources", headers=admin, json={"url": url})
        assert r.status_code == 422
    assert queue.sent == []


def test_adding_a_source_queues_ingestion(admin, queue):
    url, r = add(admin)
    assert r.status_code == 202
    assert r.json()["status"] == "pending" and r.json()["chunk_count"] == 0
    assert queue.sent == [IngestSource(source_id=r.json()["id"])]
    assert get_source(admin, url)["status"] == "pending"


def test_duplicate_url_conflicts(admin, queue):
    url, _ = add(admin)
    assert client.post(f"{P}/sources", headers=admin, json={"url": url}).status_code == 409
    assert len(queue.sent) == 1


def test_queue_down_removes_the_source_so_it_can_be_retried(admin, queue):
    url = new_url()
    queue.fail = True
    assert add(admin, url)[1].status_code == 503
    assert all(s["url"] != url for s in client.get(f"{P}/sources", headers=admin).json())
    queue.fail = False
    assert add(admin, url)[1].status_code == 202


def test_students_do_not_see_error_details(admin, student, queue):
    url, _ = add(admin)
    with SessionLocal() as db:
        src = db.scalar(select(Source).where(Source.url == url))
        assert src is not None
        src.status, src.error = SourceStatus.failed, "The page returned HTTP 500"
        db.commit()
    assert get_source(admin, url)["error"] == "The page returned HTTP 500"
    assert get_source(student, url)["status"] == "failed"
    assert get_source(student, url)["error"] is None


# --- access ---------------------------------------------------------------------------------

def test_student_can_list_but_not_modify(admin, student, queue):
    url, _ = add(admin)
    assert client.get(f"{P}/sources", headers=student).status_code == 200
    assert client.post(f"{P}/sources", headers=student, json={"url": new_url()}).status_code == 403
    sid = get_source(admin, url)["id"]
    assert client.delete(f"{P}/sources/{sid}", headers=student).status_code == 403
    assert client.post(f"{P}/samples", headers=student, json={"samples": []}).status_code == 403


# --- delete ---------------------------------------------------------------------------------

def test_delete_removes_source_and_chunks(admin):
    sid = add_ready_source("S3", S3_TEXT * 6)
    assert client.delete(f"{P}/sources/{sid}", headers=admin).status_code == 204
    with SessionLocal() as db:
        left = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.source_id == sid))
    assert left == 0


def test_delete_unknown_source_404(admin):
    assert client.delete(f"{P}/sources/999999", headers=admin).status_code == 404


# --- retrieval (pgvector) -------------------------------------------------------------------

def test_similarity_search_ranks_relevant_chunk_first():
    ids = [add_ready_source("S3", S3_TEXT * 2), add_ready_source("VPC", VPC_TEXT * 2)]
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


def test_create_samples_and_queue_their_embeddings(admin, queue):
    r = post_samples(admin, sample(), sample(task_statement=None, domain_id=4))
    assert r.status_code == 201
    body = r.json()
    assert body["created"] == 2 and len(body["ids"]) == 2
    assert queue.sent == [EmbedSamples(sample_ids=body["ids"])]
    with SessionLocal() as db:
        first, second = (db.get(SampleQuestion, i) for i in body["ids"])
        assert first is not None and second is not None
        assert first.domain_id == 1 and first.task_statement_id is not None
        assert second.domain_id == 4 and second.task_statement_id is None
        assert first.embedding is None  # the worker fills it in


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
def test_invalid_samples_rejected(admin, queue, bad):
    assert post_samples(admin, bad).status_code == 422


def test_empty_samples_rejected(admin, queue):
    assert client.post(f"{P}/samples", headers=admin, json={"samples": []}).status_code == 422


def test_batch_is_all_or_nothing(admin, queue):
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(SampleQuestion))
    assert post_samples(admin, sample(), sample(task_statement="9.9")).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SampleQuestion)) == before


def test_queue_down_removes_the_samples(admin, queue):
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(SampleQuestion))
    queue.fail = True
    assert post_samples(admin, sample()).status_code == 503
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SampleQuestion)) == before

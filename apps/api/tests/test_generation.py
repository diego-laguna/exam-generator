import pytest
from sqlalchemy import select

from app.config import get_settings
from exam_core.db import SessionLocal
from exam_core.models import BankQuestion, DocumentStatus, GenerationJob, JobStatus
from exam_core.queue import RunGeneration
from tests.helpers_api import P, bank_questions, client, new_teacher, ready_document


@pytest.fixture
def teacher():
    return new_teacher()


def start(teacher, doc_id, **body):
    return client.post(f"{P}/generations", headers=teacher, json={"document_ids": [doc_id], "mcq_count": 1, **body})


def test_starting_a_generation_queues_a_job(queue, teacher):
    doc_id = ready_document(teacher)
    r = start(teacher, doc_id, mcq_count=2, true_false_count=1, focus="  chlorophyll ")
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and job["requested_count"] == 3 and job["produced_count"] == 0
    assert job["document_ids"] == [doc_id] and job["focus"] == "chlorophyll"
    assert queue.sent == [RunGeneration(job_id=job["id"])]


def test_generation_works_without_an_llm_key_on_the_api(queue, teacher):
    """The key lives on the worker; the API only queues."""
    assert start(teacher, ready_document(teacher)).status_code == 202


def test_queue_down_marks_the_job_failed_and_unblocks(queue, teacher):
    doc_id = ready_document(teacher)
    queue.fail = True
    r = start(teacher, doc_id)
    assert r.status_code == 503 and r.json()["code"] == "QUEUE_UNAVAILABLE"
    job = client.get(f"{P}/generations", headers=teacher).json()[0]
    assert job["status"] == "failed" and job["error"] == "The job could not be queued"
    queue.fail = False
    assert start(teacher, doc_id).status_code == 202  # the failed job does not block a retry


def test_request_validation(queue, teacher):
    doc_id = ready_document(teacher)
    post = lambda **b: client.post(f"{P}/generations", headers=teacher, json={"document_ids": [doc_id], **b})  # noqa: E731
    assert post().status_code == 422  # no questions requested
    assert post(mcq_count=get_settings().generation_max_questions + 1).status_code == 422
    assert post(mcq_count=-1).status_code == 422


def test_only_own_ready_documents_can_be_used(queue, teacher):
    doc_id = ready_document(teacher)
    other = new_teacher()
    assert start(other, doc_id).status_code == 404
    assert start(teacher, 10**9).status_code == 404
    with SessionLocal() as db:
        from exam_core.models import Document

        doc = db.get(Document, doc_id)
        assert doc is not None
        doc.status = DocumentStatus.processing
        db.commit()
    r = start(teacher, doc_id)
    assert r.status_code == 409 and r.json()["code"] == "DOCUMENT_NOT_READY"
    assert not queue.sent


def test_jobs_are_private_and_one_runs_at_a_time(queue, teacher):
    doc_id = ready_document(teacher)
    job = start(teacher, doc_id).json()
    other = new_teacher()
    assert client.get(f"{P}/generations/{job['id']}", headers=other).status_code == 404
    assert client.get(f"{P}/generations", headers=other).json() == []
    r = start(teacher, doc_id)  # the first job is still queued
    assert r.status_code == 409 and r.json()["code"] == "JOB_IN_PROGRESS"
    assert len(queue.sent) == 1


def test_stale_job_is_reported_failed_and_unblocks(queue, teacher, monkeypatch):
    doc_id = ready_document(teacher)
    job = start(teacher, doc_id).json()
    with SessionLocal() as db:
        row = db.get(GenerationJob, job["id"])
        assert row is not None
        row.status = JobStatus.running
        db.commit()
    monkeypatch.setattr(get_settings(), "job_stale_minutes", 0)
    assert client.get(f"{P}/generations/{job['id']}", headers=teacher).json()["status"] == "failed"
    assert start(teacher, doc_id).status_code == 202


def test_questions_survive_document_deletion_with_their_citations(queue, storage, teacher):
    doc_id = ready_document(teacher)
    qid = bank_questions(teacher, doc_id)[0]
    client.delete(f"{P}/documents/{doc_id}", headers=teacher)
    q = client.get(f"{P}/questions/{qid}", headers=teacher).json()
    assert q["document_id"] is None
    assert q["citations"][0]["document"] == "lesson.pdf" and q["citations"][0]["page"] == 1


def test_questions_are_private_and_filterable(queue, teacher):
    doc_id = ready_document(teacher)
    ids = bank_questions(teacher, doc_id, mcq=1, true_false=1)
    qid = ids[0]
    other = new_teacher()
    assert client.get(f"{P}/questions/{qid}", headers=other).status_code == 404
    assert client.delete(f"{P}/questions/{qid}", headers=other).status_code == 404
    assert client.get(f"{P}/questions", headers=other).json() == []
    only_tf = client.get(f"{P}/questions", headers=teacher, params={"type": "true_false", "document_id": doc_id}).json()
    assert [q["type"] for q in only_tf] == ["true_false"]
    assert client.delete(f"{P}/questions/{qid}", headers=teacher).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(BankQuestion).where(BankQuestion.id == qid)) is None

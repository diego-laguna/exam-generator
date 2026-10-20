import uuid

from sqlalchemy import func, select

from app.config import get_settings
from exam_core.db import SessionLocal
from exam_core.models import Document, DocumentChunk, DocumentStatus
from exam_core.queue import IngestDocument
from exam_core.testing import LESSON, make_pdf
from tests.helpers_api import P, client, new_teacher, owner_id_of, ready_document

import pytest


@pytest.fixture
def teacher():
    return new_teacher()


def unique_pdf():
    tag = uuid.uuid4().hex
    pages = [list(p) for p in LESSON]
    pages[0][0] = f"{pages[0][0]} {tag}"
    return make_pdf(pages)


def upload(teacher, data=None, name="lesson.pdf"):
    return client.post(
        f"{P}/documents", headers=teacher, files={"file": (name, data or unique_pdf(), "application/pdf")}
    )


def test_upload_stores_the_file_and_queues_processing(storage, queue, teacher):
    r = upload(teacher)
    assert r.status_code == 202, r.text
    doc = r.json()
    assert doc["status"] == "pending" and doc["filename"] == "lesson.pdf" and doc["chunk_count"] == 0
    assert len(storage.objects) == 1
    assert queue.sent == [IngestDocument(document_id=doc["id"])]
    with SessionLocal() as db:
        row = db.get(Document, doc["id"])
        assert row is not None and row.storage_key in storage.objects and row.owner_id == owner_id_of(teacher)


def test_non_pdf_is_rejected(storage, queue, teacher):
    r = upload(teacher, data=b"just text", name="notes.txt")
    assert r.status_code == 422
    assert not storage.objects and not queue.sent


def test_duplicate_upload_conflicts(storage, queue, teacher):
    data = unique_pdf()
    assert upload(teacher, data).status_code == 202
    assert upload(teacher, data).status_code == 409
    assert len(storage.objects) == 1 and len(queue.sent) == 1


def test_size_limit(storage, queue, teacher, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_max_bytes", 500)
    assert upload(teacher).status_code == 413
    assert not storage.objects and not queue.sent


def test_filename_is_sanitized(storage, queue, teacher):
    r = upload(teacher, name="../../etc/passwd.pdf")
    assert r.json()["filename"] == "passwd.pdf"
    assert all(k.startswith("documents/") and k.endswith(".pdf") for k in storage.objects)


def test_queue_down_rolls_the_upload_back_and_can_be_retried(storage, queue, teacher):
    data = unique_pdf()
    queue.fail = True
    r = upload(teacher, data)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "QUEUE_UNAVAILABLE"
    assert not storage.objects and client.get(f"{P}/documents", headers=teacher).json() == []
    queue.fail = False
    assert upload(teacher, data).status_code == 202  # same file: nothing was left behind


def test_documents_are_private_to_their_owner(storage, queue, teacher):
    doc_id = upload(teacher).json()["id"]
    other = new_teacher()
    assert client.get(f"{P}/documents/{doc_id}", headers=other).status_code == 404
    assert client.delete(f"{P}/documents/{doc_id}", headers=other).status_code == 404
    assert doc_id not in [d["id"] for d in client.get(f"{P}/documents", headers=other).json()]
    assert doc_id in [d["id"] for d in client.get(f"{P}/documents", headers=teacher).json()]


def test_status_and_chunk_count_come_from_the_database(storage, queue, teacher):
    doc_id = ready_document(teacher)
    doc = client.get(f"{P}/documents/{doc_id}", headers=teacher).json()
    assert doc["status"] == "ready" and doc["page_count"] == 2 and doc["chunk_count"] == 1


def test_stuck_document_is_reported_failed(storage, queue, teacher, monkeypatch):
    doc_id = upload(teacher).json()["id"]
    monkeypatch.setattr(get_settings(), "job_stale_minutes", 0)
    doc = client.get(f"{P}/documents/{doc_id}", headers=teacher).json()
    assert doc["status"] == DocumentStatus.failed and "timed out" in doc["error"]


def test_delete_removes_chunks_and_stored_file(storage, queue, teacher):
    doc_id = upload(teacher).json()["id"]
    with SessionLocal() as db:  # the worker would have created chunks
        from exam_core.testing import FakeEmbedder

        db.add(DocumentChunk(document_id=doc_id, position=0, lines=[[1, 1, "x"]], content="x", embedding=FakeEmbedder().embed(["x"])[0]))
        db.commit()
    assert client.delete(f"{P}/documents/{doc_id}", headers=teacher).status_code == 204
    assert not storage.objects
    with SessionLocal() as db:
        assert db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)) == 0
    assert client.get(f"{P}/documents/{doc_id}", headers=teacher).status_code == 404

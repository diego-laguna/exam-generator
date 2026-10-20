import uuid

import pytest
from exam_core.db import SessionLocal
from exam_core.models import Document, DocumentChunk, DocumentStatus, Role
from exam_core.testing import LESSON, FakeEmbedder, MemoryStorage, create_user, make_pdf
from sqlalchemy import select

from worker.document_ingestion import ingest_document


@pytest.fixture
def storage():
    return MemoryStorage()


def upload(storage, data: bytes | None = None, status=DocumentStatus.pending) -> int:
    """What the API leaves behind: the file in storage and a pending row."""
    data = data or make_pdf(LESSON)
    key = f"documents/{uuid.uuid4().hex}.pdf"
    storage.put(key, data)
    with SessionLocal() as db:
        owner = create_user(db, Role.teacher)
        doc = Document(
            owner_id=owner.id, filename="lesson.pdf", sha256=uuid.uuid4().hex, size_bytes=len(data),
            storage_key=key, status=status,
        )
        db.add(doc)
        db.commit()
        return doc.id


def state(doc_id: int) -> Document:
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert doc is not None
        return doc


def test_processes_pdf_into_numbered_embedded_chunks(storage):
    doc_id = upload(storage)
    ingest_document(doc_id, storage, FakeEmbedder())
    doc = state(doc_id)
    assert doc.status == DocumentStatus.ready and doc.page_count == 2 and doc.error is None
    with SessionLocal() as db:
        chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)))
    assert len(chunks) == 1
    assert chunks[0].lines[0][:2] == [1, 1] and chunks[0].lines[-1][:2] == [2, 3]
    assert len(chunks[0].embedding) == 384


def test_unreadable_pdf_is_marked_failed_with_a_safe_message(storage):
    doc_id = upload(storage, b"%PDF-1.4 garbage " + uuid.uuid4().hex.encode())
    ingest_document(doc_id, storage, FakeEmbedder())
    doc = state(doc_id)
    assert doc.status == DocumentStatus.failed and doc.error
    assert "Traceback" not in doc.error


def test_scanned_pdf_without_text_fails(storage):
    doc_id = upload(storage, make_pdf([[""]]))
    ingest_document(doc_id, storage, FakeEmbedder())
    doc = state(doc_id)
    assert doc.status == DocumentStatus.failed and doc.error and "no extractable text" in doc.error


def test_missing_file_fails_without_leaking_details(storage):
    doc_id = upload(storage)
    storage.objects.clear()
    ingest_document(doc_id, storage, FakeEmbedder())
    doc = state(doc_id)
    assert doc.status == DocumentStatus.failed and doc.error == "Processing failed unexpectedly"


def test_redelivered_message_for_a_finished_document_is_ignored(storage):
    doc_id = upload(storage)
    ingest_document(doc_id, storage, FakeEmbedder())
    storage.objects.clear()  # a second run would now fail; it must not even try
    ingest_document(doc_id, storage, FakeEmbedder())
    assert state(doc_id).status == DocumentStatus.ready


def test_a_document_left_processing_by_a_dead_worker_is_picked_up_again(storage):
    doc_id = upload(storage, status=DocumentStatus.processing)
    ingest_document(doc_id, storage, FakeEmbedder())
    assert state(doc_id).status == DocumentStatus.ready


def test_failed_documents_are_not_retried(storage):
    doc_id = upload(storage, status=DocumentStatus.failed)
    ingest_document(doc_id, storage, FakeEmbedder())
    assert state(doc_id).status == DocumentStatus.failed


def test_deleted_document_is_ignored(storage):
    ingest_document(10**9, storage, FakeEmbedder())

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.embeddings import get_embedder
from app.main import app
from app.models import DocumentChunk
from app.storage import get_storage
from tests.helpers_ingestion import FakeEmbedder
from tests.helpers_teacher import LESSON, MemoryStorage, make_pdf

P = "/api/v1"
client = TestClient(app)


def login(username, password):
    r = client.post(f"{P}/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def new_teacher():
    admin = login("alice", "wonderland")
    name = f"teacher_{uuid.uuid4().hex[:8]}"
    r = client.post(f"{P}/users", headers=admin, json={"username": name, "password": "teacher-pass", "role": "teacher"})
    assert r.status_code == 201
    return login(name, "teacher-pass")


@pytest.fixture
def storage():
    fake = MemoryStorage()
    app.dependency_overrides[get_storage] = lambda: fake
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    yield fake
    app.dependency_overrides.pop(get_storage, None)
    app.dependency_overrides.pop(get_embedder, None)


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


def test_upload_processes_pdf_and_stores_numbered_chunks(storage, teacher):
    r = upload(teacher)
    assert r.status_code == 202, r.text
    # TestClient runs background tasks before returning, so the document is already processed.
    doc = client.get(f"{P}/documents/{r.json()['id']}", headers=teacher).json()
    assert doc["status"] == "ready" and doc["page_count"] == 2 and doc["chunk_count"] == 1
    assert doc["filename"] == "lesson.pdf" and doc["error"] is None
    assert len(storage.objects) == 1
    with SessionLocal() as db:
        chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc["id"]))
        assert chunk is not None
        assert chunk.lines[0][:2] == [1, 1] and chunk.lines[-1][:2] == [2, 3]


def test_non_pdf_is_rejected(storage, teacher):
    r = upload(teacher, data=b"just text", name="notes.txt")
    assert r.status_code == 422
    assert not storage.objects


def test_unreadable_pdf_is_marked_failed_with_a_safe_message(storage, teacher):
    r = upload(teacher, data=b"%PDF-1.4 garbage " + uuid.uuid4().hex.encode())
    doc = client.get(f"{P}/documents/{r.json()['id']}", headers=teacher).json()
    assert doc["status"] == "failed" and doc["error"]
    assert "Traceback" not in doc["error"]


def test_scanned_pdf_without_text_fails(storage, teacher):
    blank = make_pdf([[""]])  # a page with no text layer
    r = upload(teacher, data=blank + b"\n%" + uuid.uuid4().hex.encode())
    doc = client.get(f"{P}/documents/{r.json()['id']}", headers=teacher).json()
    assert doc["status"] == "failed" and "no extractable text" in doc["error"]


def test_duplicate_upload_conflicts(storage, teacher):
    data = unique_pdf()
    assert upload(teacher, data).status_code == 202
    assert upload(teacher, data).status_code == 409
    assert len(storage.objects) == 1


def test_size_limit(storage, teacher, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_max_bytes", 500)
    assert upload(teacher).status_code == 413
    assert not storage.objects


def test_filename_is_sanitized(storage, teacher):
    r = upload(teacher, name="../../etc/passwd.pdf")
    assert r.json()["filename"] == "passwd.pdf"
    assert all(k.startswith("documents/") and k.endswith(".pdf") for k in storage.objects)


def test_documents_are_private_to_their_owner(storage, teacher):
    doc_id = upload(teacher).json()["id"]
    other = new_teacher()
    assert client.get(f"{P}/documents/{doc_id}", headers=other).status_code == 404
    assert client.delete(f"{P}/documents/{doc_id}", headers=other).status_code == 404
    assert doc_id not in [d["id"] for d in client.get(f"{P}/documents", headers=other).json()]
    assert doc_id in [d["id"] for d in client.get(f"{P}/documents", headers=teacher).json()]


def test_delete_removes_chunks_and_stored_file(storage, teacher):
    doc_id = upload(teacher).json()["id"]
    assert client.delete(f"{P}/documents/{doc_id}", headers=teacher).status_code == 204
    assert not storage.objects
    with SessionLocal() as db:
        assert db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)) == 0
    assert client.get(f"{P}/documents/{doc_id}", headers=teacher).status_code == 404

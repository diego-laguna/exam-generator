import uuid

from exam_core.db import SessionLocal
from exam_core.errors import IngestionError
from exam_core.models import Chunk, Source, SourceStatus
from exam_core.testing import FakeEmbedder
from sqlalchemy import func, select

from tests.helpers import FakeFetcher, page
from worker.source_ingestion import ingest_source

embedder = FakeEmbedder()

S3_TEXT = (
    "Amazon S3 is object storage built to store and retrieve any amount of data. "
    "Objects live in buckets and S3 offers eleven nines of durability across storage classes. "
)


def pending_source() -> tuple[int, str]:
    url = f"https://docs.aws.amazon.com/test/{uuid.uuid4().hex}"
    with SessionLocal() as db:
        src = Source(url=url, status=SourceStatus.pending)
        db.add(src)
        db.commit()
        return src.id, url


def run(content, status=None):
    sid, url = pending_source()
    if status:
        with SessionLocal() as db:
            src = db.get(Source, sid)
            assert src is not None
            src.status = status
            db.commit()
    fetcher = FakeFetcher({url: content})
    ingest_source(sid, fetcher, embedder)
    with SessionLocal() as db:
        src = db.get(Source, sid)
        assert src is not None
        count = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.source_id == sid))
        return src, count, fetcher


def test_source_becomes_ready_with_title_and_chunks():
    src, count, fetcher = run(page("S3 Guide", ("Storage", S3_TEXT * 4), ("Security", S3_TEXT)))
    assert src.status == SourceStatus.ready and src.title == "S3 Guide" and src.error is None
    assert count and count >= 2
    assert fetcher.calls == [src.url]


def test_chunks_store_heading_and_embedding():
    src, _, _ = run(page("T", ("Durability", S3_TEXT * 2)))
    with SessionLocal() as db:
        chunk = db.scalars(select(Chunk).where(Chunk.source_id == src.id)).first()
        assert chunk is not None
        assert chunk.meta == {"heading": "Durability"}
        assert len(chunk.embedding) == 384
        assert chunk.content.startswith("Durability")


def test_failed_fetch_marks_source_failed():
    src, count, _ = run(IngestionError("The page returned HTTP 404"))
    assert src.status == SourceStatus.failed and src.error == "The page returned HTTP 404" and count == 0


def test_unexpected_error_does_not_leak_details():
    src, _, _ = run(RuntimeError("secret internal detail"))
    assert src.status == SourceStatus.failed and src.error is not None and "secret" not in src.error


def test_empty_page_fails():
    src, _, _ = run("<html><body><p>hi</p></body></html>")
    assert src.status == SourceStatus.failed and src.error is not None and "No readable content" in src.error


def test_redelivery_ignores_finished_sources_and_resumes_interrupted_ones():
    done, count, _ = run(page("T", ("H", S3_TEXT * 2)))
    fetcher = FakeFetcher({})
    ingest_source(done.id, fetcher, embedder)  # nothing to fetch: a repeat must not even try
    assert fetcher.calls == []
    resumed, count, _ = run(page("T", ("H", S3_TEXT * 2)), status=SourceStatus.ingesting)
    assert resumed.status == SourceStatus.ready and count


def test_source_deleted_during_ingestion_is_handled():
    """The job must not crash if the row disappears while it works."""
    sid, _ = pending_source()

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

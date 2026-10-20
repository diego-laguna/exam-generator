import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from exam_core.config import get_settings
from exam_core.db import SessionLocal
from exam_core.embeddings import Embedder
from exam_core.errors import IngestionError
from exam_core.models import Document, DocumentChunk, DocumentStatus
from worker.pdf_text import chunk_lines, extract_lines, lines_to_json
from exam_core.storage import Storage

log = logging.getLogger(__name__)


def _fresh(db: Session, document_id: int) -> Document | None:
    return db.scalar(
        select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
    )


def ingest_document(
    document_id: int,
    storage: Storage,
    embedder: Embedder,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    """Worker job: read the stored PDF, extract numbered lines, chunk, embed, store. Never raises."""
    settings = get_settings()
    with session_factory() as db:
        document = db.get(Document, document_id)
        # `processing` is claimable again: a worker that died mid-way left no chunks behind (they
        # are written together with `ready`), so a redelivered message can safely start over.
        if document is None or document.status not in (DocumentStatus.pending, DocumentStatus.processing):
            return
        document.status = DocumentStatus.processing
        db.commit()
        try:
            data = storage.get(document.storage_key)
            lines, pages = extract_lines(data, settings.pdf_max_pages)
            chunks = chunk_lines(lines, settings.pdf_chunk_max_lines, settings.pdf_chunk_overlap_lines)
            vectors = embedder.embed([c.content for c in chunks])

            document = _fresh(db, document_id)
            if document is None:  # deleted while we were working
                return
            db.add_all(
                DocumentChunk(
                    document_id=document_id,
                    position=i,
                    lines=lines_to_json(c),
                    content=c.content,
                    embedding=vec,
                )
                for i, (c, vec) in enumerate(zip(chunks, vectors))
            )
            document.page_count = pages
            document.status = DocumentStatus.ready
            document.error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            log.exception("Ingestion of document %s failed", document_id)
            document = _fresh(db, document_id)
            if document is not None:
                document.status = DocumentStatus.failed
                document.error = (
                    str(exc) if isinstance(exc, IngestionError) else "Processing failed unexpectedly"
                )
                db.commit()

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.chunking import chunk_sections, extract_sections
from exam_core.config import get_settings
from exam_core.db import SessionLocal
from exam_core.embeddings import Embedder
from exam_core.errors import IngestionError
from worker.fetching import Fetcher
from exam_core.models import Chunk, Source, SourceStatus

log = logging.getLogger(__name__)


def _fresh_source(db: Session, source_id: int) -> Source | None:
    return db.scalar(
        select(Source).where(Source.id == source_id).execution_options(populate_existing=True)
    )


def ingest_source(
    source_id: int,
    fetcher: Fetcher,
    embedder: Embedder,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    """Worker job: fetch, chunk, embed and store a source. Never raises.

    Runs in its own session; the request that queued it is long gone.
    """
    settings = get_settings()
    with session_factory() as db:
        source = db.get(Source, source_id)
        if source is None or source.status not in (SourceStatus.pending, SourceStatus.ingesting):
            return
        source.status = SourceStatus.ingesting
        db.commit()
        try:
            html = fetcher(source.url)
            title, sections = extract_sections(html)
            chunks = chunk_sections(sections, settings.chunk_max_chars, settings.chunk_overlap_chars)
            if not chunks:
                raise IngestionError("No readable content found on the page")
            vectors = embedder.embed([c.content for c in chunks])

            source = _fresh_source(db, source_id)
            if source is None:  # deleted while we were working
                return
            db.add_all(
                Chunk(
                    source_id=source_id,
                    position=i,
                    content=c.content,
                    embedding=vec,
                    meta={"heading": c.heading},
                )
                for i, (c, vec) in enumerate(zip(chunks, vectors))
            )
            source.title = title
            source.status = SourceStatus.ready
            source.error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            log.exception("Ingestion of source %s failed", source_id)
            source = _fresh_source(db, source_id)
            if source is not None:
                source.status = SourceStatus.failed
                source.error = str(exc) if isinstance(exc, IngestionError) else "Ingestion failed unexpectedly"
                db.commit()

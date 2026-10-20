"""Message type -> job function. Each job records its own outcome on its database row."""

import logging
from collections.abc import Callable

from exam_core.db import SessionLocal
from exam_core.models import SampleQuestion
from exam_core.queue import EmbedSamples, IngestDocument, IngestSource, Message, RunGeneration
from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.document_ingestion import ingest_document
from worker.question_gen import run_generation
from worker.services import Services
from worker.source_ingestion import ingest_source

log = logging.getLogger(__name__)


def embed_samples(
    sample_ids: list[int], services: Services, session_factory: Callable[[], Session] = SessionLocal
) -> None:
    """Fills in the embeddings of freshly created sample questions. Safe to repeat."""
    with session_factory() as db:
        rows = list(
            db.scalars(
                select(SampleQuestion).where(
                    SampleQuestion.id.in_(sample_ids), SampleQuestion.embedding.is_(None)
                )
            )
        )
        if not rows:
            return
        for row, vector in zip(rows, services.embedder.embed([r.stem for r in rows])):
            row.embedding = vector
        db.commit()


def handle(
    message: Message, services: Services, session_factory: Callable[[], Session] = SessionLocal
) -> None:
    log.info("Handling %s", message.type)
    match message:
        case IngestDocument():
            ingest_document(message.document_id, services.storage, services.embedder, session_factory)
        case IngestSource():
            ingest_source(message.source_id, services.fetcher, services.embedder, session_factory)
        case RunGeneration():
            run_generation(message.job_id, services.llm, services.embedder, session_factory)
        case EmbedSamples():
            embed_samples(message.sample_ids, services, session_factory)

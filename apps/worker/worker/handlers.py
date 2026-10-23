"""Message type -> job function. Each job records its own outcome on its database row."""

import logging
import time
from collections.abc import Callable

from exam_core.db import SessionLocal
from exam_core.models import SampleQuestion
from exam_core.queue import EmbedSamples, IngestDocument, IngestSource, Message, RunGeneration
from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.document_ingestion import ingest_document
from worker.outcome import Outcome
from worker.question_gen import run_generation
from worker.services import Services
from worker.source_ingestion import ingest_source

log = logging.getLogger(__name__)


def embed_samples(
    sample_ids: list[int], services: Services, session_factory: Callable[[], Session] = SessionLocal
) -> Outcome:
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
            return "skipped"
        for row, vector in zip(rows, services.embedder.embed([r.stem for r in rows])):
            row.embedding = vector
        db.commit()
        log.info("Samples embedded", extra={"count": len(rows)})
        return "done"


def job_id_of(message: Message) -> int | list[int]:
    """The id of the row the message names (for log context)."""
    match message:
        case IngestDocument():
            return message.document_id
        case IngestSource():
            return message.source_id
        case RunGeneration():
            return message.job_id
        case EmbedSamples():
            return message.sample_ids


def _dispatch(message: Message, services: Services, session_factory: Callable[[], Session]) -> Outcome:
    match message:
        case IngestDocument():
            return ingest_document(message.document_id, services.storage, services.embedder, session_factory)
        case IngestSource():
            return ingest_source(message.source_id, services.fetcher, services.embedder, session_factory)
        case RunGeneration():
            return run_generation(message.job_id, services.llm, services.embedder, session_factory)
        case EmbedSamples():
            return embed_samples(message.sample_ids, services, session_factory)


def handle(
    message: Message, services: Services, session_factory: Callable[[], Session] = SessionLocal
) -> None:
    """Runs the job with start/end lines. Log context (message_type, job_id) is set by the caller."""
    log.info("Job started")
    started = time.perf_counter()
    try:
        outcome = _dispatch(message, services, session_factory)
    except Exception:
        log.exception(
            "Job crashed", extra={"outcome": "crashed", "duration_ms": round((time.perf_counter() - started) * 1000)}
        )
        raise
    log.info("Job finished", extra={"outcome": outcome, "duration_ms": round((time.perf_counter() - started) * 1000)})

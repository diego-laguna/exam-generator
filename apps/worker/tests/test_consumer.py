import threading
import time

import pytest
from exam_core.db import SessionLocal
from exam_core.models import Domain, Role, SampleQuestion
from exam_core.queue import EmbedSamples, IngestDocument, Received, RunGeneration, decode, encode
from exam_core.testing import FakeEmbedder, MemoryStorage, create_user, seed_ready_document
from pydantic import ValidationError

from tests.helpers import FakeFetcher
from worker import consumer
from worker.handlers import embed_samples, handle
from worker.services import Services


class FakeQueue:
    def __init__(self, batches=()):
        self.batches = list(batches)
        self.deleted: list[str] = []
        self.extended: list[tuple[str, int]] = []

    def receive(self, wait_seconds, visibility_seconds):
        return self.batches.pop(0) if self.batches else []

    def delete(self, receipt):
        self.deleted.append(receipt)

    def extend(self, receipt, visibility_seconds):
        self.extended.append((receipt, visibility_seconds))


@pytest.fixture
def services():
    return Services(storage=MemoryStorage(), embedder=FakeEmbedder(), fetcher=FakeFetcher(), llm=None)


def test_messages_round_trip_and_unknown_ones_are_rejected():
    for message in [IngestDocument(document_id=3), RunGeneration(job_id=4), EmbedSamples(sample_ids=[1, 2])]:
        assert decode(encode(message)) == message
    assert encode(IngestDocument(document_id=3)) == '{"type":"ingest_document","document_id":3}'
    for bad in ["not json", '{"type":"drop_database"}', '{"type":"ingest_document"}']:
        with pytest.raises(ValidationError):
            decode(bad)


def test_finished_message_is_deleted(services):
    queue, seen = FakeQueue(), []
    consumer.process(queue, Received("r1", encode(RunGeneration(job_id=1))), services, 60, run=lambda m, s: seen.append(m))
    assert seen == [RunGeneration(job_id=1)] and queue.deleted == ["r1"]


def test_unreadable_message_is_dropped_without_running_anything(services):
    queue, seen = FakeQueue(), []
    consumer.process(queue, Received("r1", "garbage"), services, 60, run=lambda m, s: seen.append(m))
    assert not seen and queue.deleted == ["r1"]


def test_crash_leaves_the_message_for_redelivery(services):
    def boom(message, services):
        raise MemoryError

    queue = FakeQueue()
    consumer.process(queue, Received("r1", encode(RunGeneration(job_id=1))), services, 60, run=boom)
    assert queue.deleted == []


def test_visibility_is_extended_while_a_long_job_runs(services):
    queue = FakeQueue()
    consumer.process(
        queue, Received("r1", encode(RunGeneration(job_id=1))), services, 0.2,  # type: ignore[arg-type]
        run=lambda m, s: time.sleep(0.5),
    )
    assert queue.extended and queue.extended[0] == ("r1", 0.2) and queue.deleted == ["r1"]


def test_run_forever_processes_batches_until_stopped(services):
    stop = threading.Event()
    queue = FakeQueue([[Received("a", encode(RunGeneration(job_id=1)))], [Received("b", "garbage")]])
    original = queue.receive

    def receive(wait, visibility):
        batch = original(wait, visibility)
        if not batch:
            stop.set()
        return batch

    queue.receive = receive  # type: ignore[method-assign]
    consumer.run_forever(queue, services, stop, 60, wait_seconds=0)
    assert queue.deleted == ["a", "b"]  # job 1 does not exist: a no-op job is still acknowledged


def test_receive_errors_do_not_kill_the_loop(services):
    stop = threading.Event()

    class Flaky(FakeQueue):
        calls = 0

        def receive(self, wait_seconds, visibility_seconds):
            Flaky.calls += 1
            stop.set()
            raise ConnectionError("sqs unreachable")

    stop_wait = stop.wait
    stop.wait = lambda timeout=None: stop_wait(0)  # type: ignore[method-assign]
    consumer.run_forever(Flaky(), services, stop, 60, wait_seconds=0)
    assert Flaky.calls == 1


def test_embed_samples_fills_missing_embeddings_once(services):
    with SessionLocal() as db:
        if db.get(Domain, 1) is None:
            db.add(Domain(id=1, name="Secure", weight=30))
            db.commit()
        rows = [
            SampleQuestion(domain_id=1, stem=f"A long enough sample stem number {i}", options={}, correct_option="A")
            for i in range(2)
        ]
        db.add_all(rows)
        db.commit()
        ids = [r.id for r in rows]
    handle(EmbedSamples(sample_ids=ids), services)
    with SessionLocal() as db:
        vectors = [db.get(SampleQuestion, i).embedding for i in ids]  # type: ignore[union-attr]
    assert all(v is not None and len(v) == 384 for v in vectors)
    handle(EmbedSamples(sample_ids=ids), services)  # repeating is harmless
    embed_samples([10**9], services)


def test_handle_dispatches_document_ingestion(services):
    with SessionLocal() as db:
        owner = create_user(db, Role.teacher)
        doc = seed_ready_document(db, owner.id)
    handle(IngestDocument(document_id=doc.id), services)  # already ready: acknowledged, nothing fetched
    assert not services.storage.objects


def test_processing_logs_carry_message_type_and_job_id_and_context_is_cleared(services, caplog):
    import json
    import logging

    from exam_core.logging import JsonFormatter, get_log_context

    with SessionLocal() as db:
        owner = create_user(db, Role.teacher)
        doc = seed_ready_document(db, owner.id)
    queue = FakeQueue()
    lines: list[dict] = []

    class Capture(logging.Handler):  # formats while the job's log context is still bound
        def emit(self, record):
            if record.name.startswith("worker"):
                lines.append(json.loads(JsonFormatter().format(record)))

    handler = Capture()
    logging.getLogger().addHandler(handler)
    try:
        with caplog.at_level(logging.INFO):
            consumer.process(queue, Received("r1", encode(IngestDocument(document_id=doc.id))), services, 60)
    finally:
        logging.getLogger().removeHandler(handler)
    assert lines and all(l["message_type"] == "ingest_document" and l["job_id"] == doc.id for l in lines)
    end = [l for l in lines if l["message"] == "Job finished"]
    assert end and end[0]["outcome"] == "skipped" and "duration_ms" in end[0]
    assert get_log_context() == {} and queue.deleted == ["r1"]

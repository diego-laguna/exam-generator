"""Receive loop: one message at a time, visibility extended while the job runs."""

import logging
import threading
from collections.abc import Callable
from typing import Protocol

from exam_core.logging import log_context
from exam_core.queue import Received, decode
from pydantic import ValidationError

from worker.handlers import handle, job_id_of
from worker.services import Services

log = logging.getLogger(__name__)


class Consumer(Protocol):
    def receive(self, wait_seconds: int, visibility_seconds: int) -> list[Received]: ...
    def delete(self, receipt: str) -> None: ...
    def extend(self, receipt: str, visibility_seconds: int) -> None: ...


def _heartbeat(queue: Consumer, receipt: str, visibility: int, done: threading.Event) -> None:
    """Keeps the message hidden while its job runs, so no second worker picks it up."""
    while not done.wait(visibility / 2):
        try:
            queue.extend(receipt, visibility)
        except Exception:
            log.warning("Could not extend message visibility", exc_info=True)


def process(
    queue: Consumer,
    received: Received,
    services: Services,
    visibility: int,
    run: Callable = handle,
) -> None:
    """Runs one message. It is deleted when the job finished (successfully or recorded as failed)
    or when it can never succeed; an unexpected crash leaves it for redelivery, and after a few
    receives the queue moves it to the dead-letter queue."""
    try:
        message = decode(received.body)
    except ValidationError:
        log.error("Dropping unreadable message: %.200s", received.body)
        queue.delete(received.receipt)
        return
    with log_context(message_type=message.type, job_id=job_id_of(message)):
        done = threading.Event()
        beat = threading.Thread(target=_heartbeat, args=(queue, received.receipt, visibility, done), daemon=True)
        beat.start()
        try:
            run(message, services)
        except Exception:
            log.exception("Job failed unexpectedly; leaving the message for redelivery")
            return
        finally:
            done.set()
            beat.join(timeout=5)
        queue.delete(received.receipt)


def run_forever(
    queue: Consumer,
    services: Services,
    stop: threading.Event,
    visibility: int,
    wait_seconds: int = 20,
) -> None:
    while not stop.is_set():
        try:
            batch = queue.receive(wait_seconds, visibility)
        except Exception:
            log.exception("Receiving failed; retrying shortly")
            stop.wait(5)
            continue
        for received in batch:
            process(queue, received, services, visibility)

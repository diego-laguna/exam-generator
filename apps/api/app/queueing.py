"""Sending background work to the queue; the worker app does the work (apps/worker)."""

import logging
from collections.abc import Callable
from typing import Annotated

from exam_core.queue import Message, Queue, QueueNotConfigured, get_sqs_queue
from exam_core.errors import ServiceUnavailable
from fastapi import Depends

log = logging.getLogger(__name__)


def get_queue() -> Queue:
    try:
        return get_sqs_queue()
    except QueueNotConfigured:
        raise ServiceUnavailable("Background processing is not configured", code="QUEUE_NOT_CONFIGURED")


QueueDep = Annotated[Queue, Depends(get_queue)]


def enqueue(queue: Queue, message: Message, undo: Callable[[], None]) -> None:
    """Sends `message`. If the queue is down, runs `undo` (it removes or fails the row that would
    otherwise wait forever) and answers 503, so the caller can simply retry."""
    try:
        queue.send(message)
    except Exception:
        log.exception("Could not queue %s", message.type)
        undo()
        raise ServiceUnavailable("Could not queue the job; please try again", code="QUEUE_UNAVAILABLE")

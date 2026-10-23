import logging
import signal
import threading

from exam_core.config import get_settings
from exam_core.logging import configure_logging
from exam_core.queue import get_sqs_queue

from worker.consumer import run_forever
from worker.services import build_services


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    stop = threading.Event()
    # ECS sends SIGTERM on deploys: finish the current job, then exit.
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    queue = get_sqs_queue()
    services = build_services()
    logging.getLogger(__name__).info("Worker started", extra={"generation": "on" if services.llm else "off: no API key"})
    run_forever(queue, services, stop, settings.worker_visibility_seconds)


if __name__ == "__main__":
    main()

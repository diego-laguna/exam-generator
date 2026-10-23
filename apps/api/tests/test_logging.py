import json
import logging

from exam_core.logging import JsonFormatter, bind_log_context, clear_log_context, configure_logging, log_context


def _record(msg="hello", **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord("x.y", logging.INFO, __file__, 1, msg, None, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_json_format_fields_and_extras():
    data = json.loads(JsonFormatter().format(_record(job_id=7)))
    assert data["level"] == "INFO" and data["logger"] == "x.y" and data["message"] == "hello"
    assert data["job_id"] == 7
    assert data["timestamp"].endswith("+00:00")


def test_json_format_exception():
    try:
        raise ValueError("bad")
    except ValueError:
        import sys

        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    assert "ValueError: bad" in json.loads(JsonFormatter().format(rec))["exc_info"]


def test_context_is_added_and_restored():
    clear_log_context()
    with log_context(request_id="r1"):
        assert json.loads(JsonFormatter().format(_record()))["request_id"] == "r1"
        with log_context(job_id=3):
            data = json.loads(JsonFormatter().format(_record()))
            assert data["request_id"] == "r1" and data["job_id"] == 3
    assert "request_id" not in json.loads(JsonFormatter().format(_record()))
    bind_log_context(a=1)
    clear_log_context()
    assert "a" not in json.loads(JsonFormatter().format(_record()))


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("INFO", "json")
        configure_logging("DEBUG", "text")
        ours = [h for h in root.handlers if h not in before]
        assert len(ours) == 1
    finally:
        configure_logging("INFO", "json")

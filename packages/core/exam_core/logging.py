"""Structured logging shared by the API and the worker (stdlib only).

`configure_logging()` once at startup; `log_context(...)` / `bind_log_context(...)` add fields
(request_id, message_type, job_id, ...) to every record logged in the same context.
Never log secrets, tokens, passwords or Authorization/cookie headers.
"""

import contextvars
import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

_context: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar("log_context", default={})

# Attributes every LogRecord has; anything else on a record came from `extra=`.
_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}
_HANDLER_MARK = "_exam_core_handler"


def bind_log_context(**fields: Any) -> contextvars.Token[Mapping[str, Any]]:
    """Adds fields to the current context; returns a token for `reset_log_context`."""
    return _context.set({**_context.get(), **fields})


def reset_log_context(token: contextvars.Token[Mapping[str, Any]]) -> None:
    _context.reset(token)


def clear_log_context() -> None:
    _context.set({})


def get_log_context() -> dict[str, Any]:
    return dict(_context.get())


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    token = bind_log_context(**fields)
    try:
        yield
    finally:
        reset_log_context(token)


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    fields = {k: v for k, v in vars(record).items() if k not in _RESERVED and not k.startswith("_")}
    return {**_context.get(), **fields}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        for key, value in _extras(record).items():
            data.setdefault(key, value)
        return json.dumps(data, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        extras = _extras(record)
        if extras:
            text += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return text


def configure_logging(level: str = "INFO", fmt: Literal["json", "text"] = "json") -> None:
    """Installs one stderr handler on the root logger. Safe to call again (replaces its own handler)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _HANDLER_MARK, True)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # uvicorn installs its own handlers; send its records through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # The API logs its own access line (with request id); silence uvicorn's duplicate.
    logging.getLogger("uvicorn.access").disabled = True

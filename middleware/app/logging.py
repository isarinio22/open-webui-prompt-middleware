import json
import logging
import sys
import time
from contextvars import ContextVar
from datetime import UTC, datetime

# Works like a global variable, but each request sees its own value.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Every attribute a bare LogRecord carries. Anything else on a record was passed
# through `extra=` by the caller and belongs in the JSON line. `color_message` is
# uvicorn's ANSI-coloured duplicate of its startup messages.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                line[key] = value
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Uvicorn installs its own plain-text handlers before loading the app. Drop
    # them so its startup messages go through the JSON formatter too. The access
    # logger is left alone: --no-access-log works by stripping its handlers, and
    # uvicorn would start writing access lines again if it could reach root.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # httpx logs every upstream call at INFO with the full URL; our own
    # upstream.* events cover that with more context.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)

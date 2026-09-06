"""Structured logging with request_id correlation (review P0-6).

`EKB_LOG_FORMAT=json` switches the `enterprise_ekb` logger tree to a JSON
formatter that stamps the current request_id (set per request by the ASGI
metrics middleware). Text format remains the dev default so local output stays
human-readable.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("ekb_request_id", default="")

_CONFIGURED_FORMAT: str | None = None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(""),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def new_request_id() -> str:
    return uuid.uuid4().hex


def configure_logging(log_format: str) -> None:
    """Idempotently attach the JSON formatter for the ekb logger tree."""
    global _CONFIGURED_FORMAT
    normalized = (log_format or "text").lower()
    if _CONFIGURED_FORMAT == normalized:
        return
    logger = logging.getLogger("enterprise_ekb")
    if not logger.handlers:
        handler = logging.StreamHandler()
        logger.addHandler(handler)
    if normalized == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in logger.handlers:
        handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _CONFIGURED_FORMAT = normalized

"""Structured logging helpers that redact secrets before emission."""

from __future__ import annotations

import json
import logging
import re
from typing import Any


_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|token|secret|password|[?&]state|[?&]code)(\s*[:=]\s*)([^\s,;]+)"
)
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)^(authorization|api[_-]?key|.*token.*|.*secret.*|.*password.*)$"
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SECRET_KEY_PATTERN.fullmatch(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return _SECRET_PATTERN.sub(r"\1\2[REDACTED]", value)
    return value


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

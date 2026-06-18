"""Structured logging helpers."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
    )


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, default=str))


@contextmanager
def log_timing(
    logger: logging.Logger, event: str, *, turn_id: str, **fields: Any
) -> Iterator[dict[str, Any]]:
    start = time.monotonic()
    extra: dict[str, Any] = dict(fields)
    try:
        yield extra
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_event(logger, event, turn_id=turn_id, duration_ms=duration_ms, **extra)

"""Structured (key=value) logging setup shared by scripts.

Modules log an event name as the message and attach context via ``extra``::

    logger.info("download_complete", extra={"url": url, "sha256": digest})

which renders as::

    2026-10-15T12:00:00Z INFO aircraft_cost_model.ingestion.airports download_complete url=... sha256=...
"""

from __future__ import annotations

import logging
import time

_STANDARD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class KeyValueFormatter(logging.Formatter):
    """Format records as ``timestamp level logger event key=value ...`` in UTC."""

    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%SZ')} {record.levelname} "
            f"{record.name} {record.getMessage()}"
        )
        fields = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}
        if fields:
            base += " " + " ".join(f"{k}={v!r}" if isinstance(v, str) and " " in v else f"{k}={v}"
                                   for k, v in fields.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(level: str = "INFO") -> None:
    """Install the key=value formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        if isinstance(handler.formatter, KeyValueFormatter):
            return
    handler = logging.StreamHandler()
    handler.setFormatter(KeyValueFormatter())
    root.addHandler(handler)

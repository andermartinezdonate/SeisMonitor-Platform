"""Structured JSON logging for Cloud Run services.

Outputs JSON log lines compatible with Google Cloud Logging, with fields
for source, run_id, event_count, and duration_ms.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """Outputs log records as JSON for Cloud Run structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add optional structured fields if present on the record
        for field in ("source", "run_id", "event_count", "duration_ms"):
            val = getattr(record, field, None)
            if val is not None:
                log_entry[field] = val

        # Strip None values
        log_entry = {k: v for k, v in log_entry.items() if v is not None}

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def configure_logging(level: int = logging.INFO) -> None:
    """Replace root handler with structured JSON formatter.

    Call at service startup (e.g., in main.py) before any logging.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)

"""
logging_config.py — Centralized logging setup for the KDPE project.

Call setup_logging() once at application startup (in app.py lifespan).
Every module then does:
    from logging_config import get_logger
    logger = get_logger(__name__)

Two outputs:
  logs/run.log     — human-readable rotating text log (all levels)
  logs/events.jsonl — machine-readable structured events (INFO and above)

The events.jsonl file is the primary artifact for post-hoc metric analysis.
Each line is a standalone JSON object; grep/jq can extract events by type.

Usage:
    logger.info("msg", extra={"event": "doc_extracted", "doc_id": "x", "n_entities": 5})
    # → appends one JSON line to events.jsonl
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────────────

_LOGS_DIR = Path(__file__).parent / "logs"
_LOG_FILE = _LOGS_DIR / "run.log"
_EVENTS_FILE = _LOGS_DIR / "events.jsonl"

_FMT_TEXT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_setup_done = False


# ── Custom handler: writes structured JSON events ──────────────────────────────

class _JsonlHandler(logging.Handler):
    """
    Writes one JSON object per line to events.jsonl.

    Only emits records that carry an 'event' key in record.extra.
    Regular log messages (no 'event') go only to run.log and stdout.
    """

    def __init__(self, path: Path):
        super().__init__(level=logging.INFO)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path

    def emit(self, record: logging.LogRecord) -> None:
        # Only structured events (those with an 'event' attribute)
        event_name = getattr(record, "event", None)
        if not event_name:
            return

        entry: dict = {
            "ts":     datetime.now(timezone.utc).isoformat(),
            "level":  record.levelname,
            "logger": record.name,
            "event":  event_name,
        }

        # Merge any extra scalar fields attached to the record
        _skip = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "message", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName",
            "exc_info", "exc_text", "event",
            # Python 3.12+ additions and formatter artefacts
            "taskName", "asctime",
        }
        for k, v in record.__dict__.items():
            if k not in _skip and not k.startswith("_"):
                entry[k] = v

        try:
            line = json.dumps(entry, default=str)
            with open(self._path, "a") as f:
                f.write(line + "\n")
        except Exception:
            self.handleError(record)


# ── Public API ─────────────────────────────────────────────────────────────────

def _has_our_handlers() -> bool:
    """Return True if our file handler is already on the root logger."""
    root = logging.getLogger()
    return any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "baseFilename", None) == str(_LOG_FILE.resolve())
        for h in root.handlers
    )


def setup_logging(level: int = logging.DEBUG) -> None:
    """
    Configure root logger with three handlers.

    Uses handler-presence detection instead of a flag so that if uvicorn
    (or any library) calls dictConfig and wipes our handlers between import
    time and the first request, calling setup_logging() again re-adds them.
    """
    if _has_our_handlers():
        return

    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any stale instances of our handlers to avoid duplicates
    root.handlers = [
        h for h in root.handlers
        if not isinstance(h, (logging.handlers.RotatingFileHandler, _JsonlHandler))
    ]

    formatter = logging.Formatter(_FMT_TEXT, datefmt=_DATE_FMT)

    # 1. Rotating file handler — keeps last 5 × 10 MB
    # Falls back silently when the log file is not writable (e.g. root-owned from Docker).
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            _LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except PermissionError:
        pass

    # 2. Stderr handler — INFO and above (stderr survives uvicorn stdout capture)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # 3. JSONL structured events handler
    jsonl_handler = _JsonlHandler(_EVENTS_FILE)
    root.addHandler(jsonl_handler)

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger. Call setup_logging() first."""
    return logging.getLogger(name)

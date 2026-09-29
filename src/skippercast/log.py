"""Structured logging for scheduled jobs (standard library only).

    from skippercast import log
    logger = log.configure(job="forecast-build")
    logger.info("model built", extra={"source_id": "gfs_global", "duration_ms": 31800})

Records go to stderr (stdout stays free for a command's machine-readable
result). Each record is one JSON object per line with `ts`, `level`, `logger`,
`msg` and, when known, the structured fields in FIELDS; `run_id` and `job` are
filled from configure(). A human-readable line is used instead when stderr is a
terminal (stdout is a TTY) or SKIPPERCAST_LOG=text; SKIPPERCAST_LOG=json forces
JSON.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import sys

ROOT = "skippercast"
FIELDS = ("run_id", "job", "region", "source_id", "duration_ms", "http_status", "error_class")
_HANDLER_FLAG = "_skippercast_handler"


def run_id(environ=None):
    """The GitHub Actions run id, as feeds record it, or a UTC-stamped local id outside Actions."""
    environ = os.environ if environ is None else environ
    ident = (environ.get("GITHUB_RUN_ID") or "").strip()
    return ident or "local-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class ContextFilter(logging.Filter):
    """Adds the job-wide fields (run_id, job, ...) to records that did not set them."""

    def __init__(self, **context):
        super().__init__()
        self.context = {k: v for k, v in context.items() if v is not None}

    def filter(self, record):
        for key, value in self.context.items():
            if getattr(record, key, None) is None:
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    """One compact JSON object per record; unknown values are stringified, never dropped silently."""

    def format(self, record):
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            entry.setdefault("error_class", record.exc_info[0].__name__)
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str, allow_nan=False)


class TextFormatter(logging.Formatter):
    """Short line for people at a terminal: time, level, context, message, measurements."""

    def format(self, record):
        stamp = datetime.fromtimestamp(record.created, timezone.utc).strftime("%H:%M:%SZ")
        where = " ".join(str(getattr(record, key)) for key in ("job", "region", "source_id")
                         if getattr(record, key, None) is not None)
        facts = " ".join(f"{key}={getattr(record, key)}" for key in ("duration_ms", "http_status", "error_class")
                         if getattr(record, key, None) is not None)
        line = f"{stamp} {record.levelname:<7} {where + ': ' if where else ''}{record.getMessage()}"
        if facts:
            line += f" ({facts})"
        if record.exc_info and record.exc_info[0] is not None:
            line += "\n" + self.formatException(record.exc_info)
        return line


def wants_text(terminal=None, environ=None):
    """Text when stdout is a terminal or SKIPPERCAST_LOG=text; JSON otherwise (CI logs, files, pipes)."""
    choice = ((os.environ if environ is None else environ).get("SKIPPERCAST_LOG") or "").strip().lower()
    if choice in ("text", "json"):
        return choice == "text"
    terminal = sys.stdout if terminal is None else terminal
    try:
        return terminal.isatty()
    except (AttributeError, ValueError):
        return False


def configure(job=None, *, run=None, level=logging.INFO, stream=None, environ=None, **context):
    """Install one handler on the `skippercast` logger and return a logger named for the job.

    Calling it again replaces the previous handler, so tests and nested entry
    points do not duplicate output. `run` defaults to run_id(environ).
    """
    stream = sys.stderr if stream is None else stream
    root = logging.getLogger(ROOT)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_FLAG, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream)
    setattr(handler, _HANDLER_FLAG, True)
    handler.setFormatter(TextFormatter() if wants_text(environ=environ) else JsonFormatter())
    handler.addFilter(ContextFilter(run_id=run or run_id(environ), job=job, **context))
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    return logging.getLogger(f"{ROOT}.{job}" if job else ROOT)


def get_logger(name):
    """A logger under the `skippercast` hierarchy (configure() decides where it goes)."""
    return logging.getLogger(name if name == ROOT or name.startswith(ROOT + ".") else f"{ROOT}.{name}")

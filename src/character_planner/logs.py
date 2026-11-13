"""Logging for the API and the worker (ADR 0019).

One setup for both processes: console output always, plus rotating files when LOG_DIR is
set (the API writes server.log and access.log, the worker writes worker.log; one file per
process, because rotating a file two processes write to isn't safe). Every line goes
through redact(), so tokens, the client secret and OAuth codes never reach a log, even
inside a traceback.
"""

import json
import logging
import logging.config
import re
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.engine import make_url

from character_planner.config import Settings

Process = Literal["api", "worker"]

ACCESS_LOGGER = "character_planner.access"
REDACTED = "[redacted]"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5
# Errors listed one by one at the end of a batch; the rest are counted.
MAX_ERRORS = 20

# The request being handled, so every line it causes can be tied back to it.
request_id: ContextVar[str] = ContextVar("request_id", default="-")

# Secrets as they appear in text: bearer tokens, token-like query and form fields, JSON
# fields, and basic-auth credentials in URLs.
_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)\b(access_token|refresh_token|id_token|client_secret|code|state|password)"
        r"(=)[^&\s\"']+"
    ),
    re.compile(
        r"(?i)(\"(?:access_token|refresh_token|id_token|client_secret|password)\"\s*:\s*\")"
        r"[^\"]*"
    ),
    re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s]+(?=@)"),
    # Discord webhook URLs carry their own credential (#12).
    re.compile(r"(?i)(/api/(?:v\d+/)?webhooks/\d+/)[A-Za-z0-9_-]+"),
]


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Text with secrets replaced by [redacted]: known secret values, then patterns."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        if pattern.groups == 2:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
        else:
            text = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return text


def safe_database_url(url: str) -> str:
    """The database URL with any password hidden, for the startup line."""
    try:
        parsed = make_url(url)
    except Exception:
        return redact(url)
    # Only rebuild URLs with a password: rendering escapes paths (C: becomes C%3A).
    return parsed.render_as_string(hide_password=True) if parsed.password else url


class RequestIdFilter(logging.Filter):
    """Adds the current request id (or "-") to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class RedactingFormatter(logging.Formatter):
    """A text formatter whose whole output, traceback included, is redacted."""

    def __init__(self, *args: Any, secrets: tuple[str, ...] = (), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self.secrets)


class JsonFormatter(RedactingFormatter):
    """One JSON object per line, for log collectors (#17)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return redact(json.dumps(entry, ensure_ascii=False), self.secrets)


TEXT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s"
ACCESS_FORMAT = "%(asctime)s %(message)s"


def logging_config(settings: Settings, process: Process) -> dict[str, Any]:
    """The dictConfig for this process."""
    secrets = (settings.bnet_client_secret.get_secret_value(),)
    formatter = "json" if settings.log_format == "json" else "text"
    debug = settings.log_level == "DEBUG"

    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": formatter,
            "filters": ["request_id"],
        },
    }
    root_handlers = ["console"]
    access_handlers = ["console"]
    if settings.log_dir is not None:
        files = {"api": "server.log", "worker": "worker.log"}
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(settings.log_dir / files[process]),
            "maxBytes": MAX_BYTES,
            "backupCount": BACKUPS,
            "encoding": "utf-8",
            "formatter": formatter,
            "filters": ["request_id"],
        }
        root_handlers.append("file")
        if process == "api":
            handlers["access_file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(settings.log_dir / "access.log"),
                "maxBytes": MAX_BYTES,
                "backupCount": BACKUPS,
                "encoding": "utf-8",
                "formatter": "json" if formatter == "json" else "access",
                "filters": ["request_id"],
            }
            # Requests go to access.log, not also to server.log.
            access_handlers = ["console", "access_file"]

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": RequestIdFilter}},
        "formatters": {
            "text": {"()": RedactingFormatter, "fmt": TEXT_FORMAT, "secrets": secrets},
            "access": {"()": RedactingFormatter, "fmt": ACCESS_FORMAT, "secrets": secrets},
            "json": {"()": JsonFormatter, "secrets": secrets},
        },
        "handlers": handlers,
        "root": {"level": settings.log_level, "handlers": root_handlers},
        "loggers": {
            ACCESS_LOGGER: {"level": "INFO", "handlers": access_handlers, "propagate": False},
            # uvicorn's own messages (startup, errors) through the same handlers; its
            # access lines are replaced by ours, which carry the request id.
            "uvicorn": {"level": "INFO", "handlers": [], "propagate": True},
            "uvicorn.error": {"level": "INFO", "handlers": [], "propagate": True},
            "uvicorn.access": {"level": "WARNING", "handlers": [], "propagate": False},
            # httpx logs each upstream request at INFO: keep them for DEBUG only.
            "httpx": {"level": "INFO" if debug else "WARNING"},
            "httpcore": {"level": "WARNING"},
            "sqlalchemy": {"level": "WARNING"},
        },
    }


def configure_logging(settings: Settings, process: Process) -> None:
    if settings.log_dir is not None:
        Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(logging_config(settings, process))


class JobLog:
    """Start, progress and end lines for a batch of upstream fetches.

    Logs what's about to happen, a progress line every `every` items, and a summary with
    the duration, so a long refresh shows what it's doing.
    """

    def __init__(self, log: logging.Logger, what: str, total: int | None, every: int = 50) -> None:
        """total is None when the batch size isn't known up front."""
        self.log, self.what, self.total, self.every = log, what, total, every
        self.started = time.perf_counter()
        if total is None:
            log.info("%s: started", what)
        else:
            log.info("%s: %d to fetch", what, total)

    def step(self, index: int) -> None:
        """Call before fetching item `index` (from 1)."""
        if index > 1 and (index - 1) % self.every == 0:
            of = f"/{self.total}" if self.total is not None else ""
            self.log.info("%s: %d%s done", self.what, index - 1, of)

    def done(self, summary: str, errors: list[str] | None = None) -> None:
        """The summary line, then each error (the first MAX_ERRORS) as a warning."""
        elapsed = time.perf_counter() - self.started
        self.log.info("%s: done in %.1fs, %s", self.what, elapsed, summary)
        errors = errors or []
        for error in errors[:MAX_ERRORS]:
            self.log.warning("%s: %s", self.what, error)
        if len(errors) > MAX_ERRORS:
            self.log.warning("%s: %d more errors", self.what, len(errors) - MAX_ERRORS)

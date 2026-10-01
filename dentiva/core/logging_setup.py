"""Application logging configuration.

* Rotating file logs under ``<data>/logs/dentiva.log`` (5 MB × 5 backups).
* Console handler for development convenience (not in frozen builds by default).
* Sensitive fields (passwords, hashes, activation codes) are redacted via a
  :class:`SensitiveDataFilter` before records are emitted.
* Logs are plaintext but never contain PHI payloads or secrets; clinical content
  is referenced by ID only.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path

from .paths_shim import paths

LOG_FILENAME = "dentiva.log"
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Patterns that should never appear in log output.
_SENSITIVE_PATTERNS = [
    re.compile(r"(password\s*[=:]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(password_hash\s*[=:]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(activation\s*[=:]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(token\s*[=:]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(authorization\s*[=:]\s*)(\S+)", re.IGNORECASE),
]


class SensitiveDataFilter(logging.Filter):
    """Redact password / token / activation values from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern in _SENSITIVE_PATTERNS:
            msg = pattern.sub(r"\1[REDACTED]", msg)
        record.msg = msg
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO, *, console: bool | None = None) -> Path:
    """Configure root logger and return the active log file path."""
    paths.ensure()
    log_path = paths.logs_dir / LOG_FILENAME

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if configure_logging is called twice (tests).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    sensitive_filter = SensitiveDataFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(sensitive_filter)
    root.addHandler(file_handler)

    if console is None:
        console = not getattr(sys, "frozen", False)
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(sensitive_filter)
        root.addHandler(console_handler)

    # Silence noisy third-party loggers.
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.WARNING)

    root.debug("Logging initialized; file=%s", log_path)
    return log_path

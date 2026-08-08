from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler

from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.core.product import PRODUCT_DISPLAY_NAME

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
_configured_signature: tuple[str, str, int] | None = None
_start_logged_for_pid: int | None = None

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret)(\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})\b"),
)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        for pattern in _SECRET_PATTERNS:
            if pattern.groups >= 3:
                rendered = pattern.sub(r"\1\2[REDACTED]", rendered)
            elif pattern.groups == 2:
                rendered = pattern.sub(r"\1[REDACTED]", rendered)
            else:
                rendered = pattern.sub("[REDACTED]", rendered)
        return rendered


class DataLogFilter(logging.Filter):
    _PREFIXES = (
        "personal_alpha_terminal.data",
        "personal_alpha_terminal.terminal.market_data",
        "personal_alpha_terminal.terminal.providers",
        "yfinance",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self._PREFIXES)


def _rotating_handler(path: str | os.PathLike[str], level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    handler._pat_handler = True  # type: ignore[attr-defined]
    return handler


def configure_logging(settings: Settings | None = None) -> None:
    """Configure idempotent, redacted and bounded product logs."""

    global _configured_signature

    resolved = settings or get_settings()
    resolved.log_dir.mkdir(parents=True, exist_ok=True)
    signature = (str(resolved.log_dir.resolve()), resolved.log_level, os.getpid())
    if _configured_signature == signature:
        return

    root = logging.getLogger()
    root.setLevel(resolved.log_level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(RedactingFormatter(LOG_FORMAT))
    console._pat_handler = True  # type: ignore[attr-defined]

    app_handler = _rotating_handler(resolved.log_dir / "app.log", logging.INFO)
    data_handler = _rotating_handler(resolved.log_dir / "data.log", logging.INFO)
    data_handler.addFilter(DataLogFilter())
    error_handler = _rotating_handler(resolved.log_dir / "error.log", logging.ERROR)

    root.addHandler(console)
    root.addHandler(app_handler)
    root.addHandler(data_handler)
    root.addHandler(error_handler)
    _configured_signature = signature


def log_application_start_once() -> None:
    """Record one process start, independent of UI refreshes."""

    global _start_logged_for_pid
    process_id = os.getpid()
    if _start_logged_for_pid == process_id:
        return
    logging.getLogger(__name__).info(
        "application_start product=%s pid=%s", PRODUCT_DISPLAY_NAME, process_id
    )
    _start_logged_for_pid = process_id

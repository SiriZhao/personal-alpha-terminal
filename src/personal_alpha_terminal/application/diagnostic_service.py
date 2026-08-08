from __future__ import annotations

import json
import platform
import re
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from personal_alpha_terminal import __build_version__
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.runtime_bootstrap import application_data_dir

SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|token|secret)(\s*[=:]\s*)(\S+)")


class DiagnosticService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def summary(self) -> dict[str, object]:
        bind = self._session.get_bind()
        table_names = inspect(bind).get_table_names()
        revision = (
            self._session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if "alembic_version" in table_names
            else "metadata-only-test"
        )
        root = application_data_dir()
        try:
            free_disk_bytes: int | str = shutil.disk_usage(root).free
        except OSError as error:
            free_disk_bytes = f"unavailable:{type(error).__name__}"
        return {
            "version": __build_version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "database": self._session.bind.dialect.name if self._session.bind else "unknown",
            "migration": revision,
            "data_directory": str(root / "data"),
            "log_directory": str(self._settings.log_dir),
            "config_directory": str(root),
            "free_disk_bytes": free_disk_bytes,
        }

    def recent_errors(self, limit: int = 50) -> tuple[str, ...]:
        log_file = self._settings.log_dir / "error.log"
        if not log_file.exists():
            log_file = self._settings.log_dir / "personal-alpha-terminal.log"
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ()
        return tuple(self._redact(line) for line in lines if " ERROR " in line)[-limit:]

    def export_bundle(self, destination: Path | None = None) -> Path:
        root = application_data_dir()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = destination or root / "diagnostics" / f"diagnostics-{stamp}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        summary = json.dumps(self.summary(), ensure_ascii=False, indent=2)
        errors = "\n".join(self.recent_errors())
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("system-summary.json", summary)
            archive.writestr("recent-errors.txt", errors)
        return target

    @staticmethod
    def _redact(value: str) -> str:
        return SECRET_PATTERN.sub(r"\1\2[REDACTED]", value)

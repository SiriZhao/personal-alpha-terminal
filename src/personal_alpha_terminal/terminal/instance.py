"""Single-instance lock for the terminal product."""

from __future__ import annotations

import json
import os
import sys
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType

from personal_alpha_terminal.core.runtime_bootstrap import (
    application_data_dir,
    process_is_running,
)


def default_console_lock_path() -> Path:
    """Resolve the per-user lock, with an explicit test/portable override."""

    override = os.environ.get("PAT_TERMINAL_RUNTIME_DIR", "").strip()
    if override:
        return Path(override) / "console-instance.json"
    return application_data_dir() / "run" / "console-instance.json"


class ConsoleInstanceLock(AbstractContextManager["ConsoleInstanceLock"]):
    """Simple per-user console lock; stale PIDs are replaced safely."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_console_lock_path()

    def __enter__(self) -> ConsoleInstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(payload["pid"])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pid = 0
        if pid and pid != os.getpid() and process_is_running(pid):
            raise RuntimeError(f"Personal Alpha Terminal is already running (PID {pid})")
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"pid": os.getpid(), "executable": sys.executable}),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if int(payload.get("pid", -1)) == os.getpid():
            self.path.unlink(missing_ok=True)

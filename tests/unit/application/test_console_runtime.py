import json
import logging
import os
from pathlib import Path

import pytest

from personal_alpha_terminal.core import logging as app_logging
from personal_alpha_terminal.tui import instance as instance_module
from personal_alpha_terminal.tui.instance import ConsoleInstanceLock


def test_console_instance_lock_rejects_another_live_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "console-instance.json"
    foreign_pid = os.getpid() + 1000
    lock_path.write_text(json.dumps({"pid": foreign_pid}), encoding="utf-8")
    monkeypatch.setattr(instance_module, "process_is_running", lambda pid: pid == foreign_pid)

    with pytest.raises(RuntimeError, match="PID"):
        ConsoleInstanceLock(lock_path).__enter__()


def test_console_instance_lock_replaces_stale_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "console-instance.json"
    lock_path.write_text(json.dumps({"pid": os.getpid() + 1000}), encoding="utf-8")
    monkeypatch.setattr(instance_module, "process_is_running", lambda _pid: False)

    with ConsoleInstanceLock(lock_path):
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["pid"] == os.getpid()
    assert not lock_path.exists()


def test_application_start_is_logged_once_per_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    logger = logging.getLogger(app_logging.__name__)
    monkeypatch.setattr(logger, "info", lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(app_logging, "_start_logged_for_pid", None)

    app_logging.log_application_start_once()
    app_logging.log_application_start_once()

    assert len(calls) == 1
    assert calls[0][-1] == os.getpid()

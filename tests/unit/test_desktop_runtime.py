import json
import socket
import threading
import urllib.request
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.desktop import launcher, runtime
from personal_alpha_terminal.desktop.recovery import (
    RecoveryStatus,
    build_recovery_server,
    recovery_html,
)


def test_bootstrap_creates_versioned_user_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("PAT_DATABASE_URL", raising=False)
    monkeypatch.delenv("PAT_LOG_DIR", raising=False)
    get_settings.cache_clear()

    settings = runtime.bootstrap_user_environment()
    database_path = tmp_path / runtime.APP_NAME / "data" / "personal_alpha.db"
    engine = create_engine(settings.database_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert database_path.exists()
    assert "alembic_version" in tables
    assert "prices" in tables
    assert (tmp_path / runtime.APP_NAME / "config.env").exists()
    status_path = tmp_path / runtime.APP_NAME / "startup-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "ready"
    assert status["database_backend"] == "sqlite"
    assert status["checks"]["database_connection"] == "ok"
    assert status["checks"]["database_migration"]
    get_settings.cache_clear()


def test_update_requires_https_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PAT_UPDATE_MANIFEST_URL", "http://example.com/latest.json")

    success, message = runtime.stage_update()

    assert not success
    assert "HTTPS" in message


def test_stop_without_pid_is_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert not runtime.stop_running_instance()


def test_choose_dashboard_port_falls_back_when_preferred_is_in_use() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((runtime.DEFAULT_HOST, 0))
        occupied_port = int(listener.getsockname()[1])

        selected_port = runtime.choose_dashboard_port(preferred_port=occupied_port)

    assert selected_port != occupied_port
    assert selected_port > 0


def test_stop_refuses_to_terminate_mismatched_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    runtime.write_instance("http://127.0.0.1:8501")
    monkeypatch.setattr(runtime, "process_matches_instance", lambda _instance: False)

    assert not runtime.stop_running_instance()
    assert not runtime.pid_file().exists()


def test_instance_metadata_rejects_non_loopback_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    with pytest.raises(ValueError, match="loopback"):
        runtime.write_instance("http://0.0.0.0:8501")


def test_runtime_asset_preflight_rejects_incomplete_archive_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard = tmp_path / "personal_alpha_terminal" / "dashboard" / "app.py"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("# dashboard", encoding="utf-8")
    missing_static = tmp_path / "streamlit" / "static"

    class FileUtil:
        @staticmethod
        def get_static_dir() -> str:
            return str(missing_static)

    monkeypatch.setattr("streamlit.file_util.get_static_dir", FileUtil.get_static_dir)

    error = launcher._runtime_asset_error(dashboard)

    assert isinstance(error, FileNotFoundError)
    assert "index.html" in str(error)


def test_runtime_asset_preflight_accepts_complete_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard = tmp_path / "personal_alpha_terminal" / "dashboard" / "app.py"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("# dashboard", encoding="utf-8")
    static = tmp_path / "streamlit" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr("streamlit.file_util.get_static_dir", lambda: str(static))

    assert launcher._runtime_asset_error(dashboard) is None


def test_recovery_dashboard_returns_http_200_and_escapes_details() -> None:
    status = RecoveryStatus(
        stage="runtime-assets<script>",
        error_type="FileNotFoundError",
        guidance="extract <all> files",
    )
    payload = recovery_html(status).decode("utf-8")
    assert "<script>" not in payload
    assert "&lt;script&gt;" in payload
    assert "Data Gate" in payload and "BLOCKED" in payload

    server = build_recovery_server(runtime.DEFAULT_HOST, 0, status)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as response:
            assert response.status == 200
            assert b"System Status" in response.read()
        with urllib.request.urlopen(
            f"http://{host}:{port}/_stcore/health", timeout=5
        ) as response:
            assert response.status == 200
            assert response.read() == b"ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

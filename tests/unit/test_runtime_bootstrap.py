import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from personal_alpha_terminal.core import runtime_bootstrap as runtime
from personal_alpha_terminal.core.config import get_settings


def test_bootstrap_creates_versioned_user_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for name in ("PAT_DATABASE_URL", "PAT_LOG_DIR"):
        monkeypatch.delenv(name, raising=False)
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
    status = json.loads(
        (tmp_path / runtime.APP_NAME / "startup-status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "ready"
    assert status["database_backend"] == "sqlite"
    assert status["checks"]["database_connection"] == "ok"
    get_settings.cache_clear()

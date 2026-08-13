import sqlite3
import zipfile
from pathlib import Path

import pytest

from personal_alpha_terminal import __build_version__, __version__
from personal_alpha_terminal.agents.llm import LLMProviderError, build_llm_provider
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.credentials import credential_target
from personal_alpha_terminal.core.diagnostics import create_diagnostic_bundle, redact_text
from personal_alpha_terminal.core.local_backup import (
    apply_pending_restore,
    create_local_backup,
    inspect_backup,
    sanitize_env_text,
    stage_restore,
)


def _settings(database: Path, log_dir: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{database.as_posix()}",
        log_dir=log_dir,
        llm_provider="disabled",
    )


def _database(path: Path, value: str = "original") -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def test_version_is_stable_terminal_baseline_110() -> None:
    assert __version__ == "1.2.0-rc.1"
    assert __build_version__ == "1.2.0-rc.1"


def test_disabled_ai_does_not_silently_call_mock() -> None:
    provider = build_llm_provider(Settings(_env_file=None, llm_provider="disabled"))
    assert provider.name == "disabled"
    with pytest.raises(LLMProviderError, match="disabled"):
        from personal_alpha_terminal.agents.llm.schemas import LLMRequest

        provider.generate(LLMRequest(system_prompt="x", user_prompt="{}", temperature=0))


def test_deepseek_base_url_requires_https() -> None:
    with pytest.raises(ValueError, match="valid HTTPS URL"):
        Settings(_env_file=None, deepseek_base_url="http://example.com")


def test_credential_targets_are_provider_scoped() -> None:
    assert credential_target("openai") != credential_target("deepseek")
    assert credential_target("anthropic") != credential_target("custom")
    with pytest.raises(ValueError, match="unsupported"):
        credential_target("unknown")


def test_backup_excludes_secrets_and_restores_on_next_start(tmp_path: Path) -> None:
    root = tmp_path / "app"
    data = root / "data"
    logs = root / "logs"
    data.mkdir(parents=True)
    logs.mkdir()
    database = data / "personal_alpha.db"
    _database(database)
    (root / "config.env").write_text(
        "PAT_LOG_LEVEL=INFO\nOPENAI_API_KEY=secret-value\n",
        encoding="utf-8",
    )
    settings = _settings(database, logs)
    archive = create_local_backup(
        settings,
        application_root=root,
        backup_directory=root / "backups",
    )
    preview = inspect_backup(archive)
    assert preview.valid
    with zipfile.ZipFile(archive) as bundle:
        config = bundle.read("config.env").decode("utf-8")
        assert "secret-value" not in config
        assert "<redacted>" in config

    connection = sqlite3.connect(database)
    try:
        connection.execute("UPDATE marker SET value='changed'")
        connection.commit()
    finally:
        connection.close()
    stage_restore(archive, application_root=root)
    assert apply_pending_restore(root, database)
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("original",)
    finally:
        connection.close()
    assert tuple((root / "backups" / "pre-restore").glob("*.db"))


def test_diagnostic_bundle_redacts_tokens_and_excludes_database(tmp_path: Path) -> None:
    root = tmp_path / "app"
    data = root / "data"
    logs = root / "logs"
    data.mkdir(parents=True)
    logs.mkdir()
    database = data / "personal_alpha.db"
    _database(database)
    (root / "config.env").write_text("DEEPSEEK_API_KEY=top-secret\n", encoding="utf-8")
    (logs / "personal-alpha-terminal.log").write_text(
        "ERROR authorization=Bearer-secret portfolio_value=999999\n",
        encoding="utf-8",
    )
    archive = create_diagnostic_bundle(
        _settings(database, logs),
        application_root=root,
        output_directory=root / "diagnostics",
    )
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        combined = b"\n".join(bundle.read(name) for name in names).decode("utf-8")
        assert "personal_alpha.db" not in names
        assert "top-secret" not in combined
        assert "Bearer-secret" not in combined
        assert "999999" not in combined
        assert "<redacted>" in combined


def test_redaction_helpers_do_not_leak_secret_values() -> None:
    assert "secret" not in sanitize_env_text("TOKEN=secret\n")
    assert "abc" not in redact_text("Authorization=abc")

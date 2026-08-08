import logging
from pathlib import Path

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.logging import configure_logging


def test_configure_logging_creates_rotating_log_file(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, log_dir=tmp_path, log_level="INFO")

    configure_logging(settings)
    logging.getLogger("test").info("logging-ready")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "logging-ready" in (tmp_path / "app.log").read_text(encoding="utf-8")
    assert (tmp_path / "data.log").exists()
    assert (tmp_path / "error.log").exists()


def test_product_logs_redact_secrets(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, log_dir=tmp_path, log_level="INFO")

    configure_logging(settings)
    logging.getLogger("test").error(
        "api_key=top-secret Authorization: Bearer bearer-secret sk-example123456"
    )
    for handler in logging.getLogger().handlers:
        handler.flush()

    payload = (tmp_path / "error.log").read_text(encoding="utf-8")
    assert "top-secret" not in payload
    assert "bearer-secret" not in payload
    assert "sk-example123456" not in payload
    assert "[REDACTED]" in payload

"""Per-user runtime bootstrap for the terminal product.

This module intentionally contains no browser, localhost, GUI, or frontend-server
contract. It owns only writable user directories, database migration and startup
verification required by the console application.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import disk_usage

from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.core.credentials import load_credentials_into_environment
from personal_alpha_terminal.core.local_backup import apply_pending_restore, ensure_daily_backup
from personal_alpha_terminal.core.product import PRODUCT_DISPLAY_NAME
from personal_alpha_terminal.core.runtime_context import production_desktop_database_url
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.migrations import upgrade_database

APP_NAME = "PersonalAlphaTerminal"
MINIMUM_FREE_DISK_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StartupStatus:
    status: str
    checked_at: str
    app_data_dir: str
    database_backend: str
    bundled_runtime: bool
    free_disk_bytes: int
    checks: dict[str, str]


def application_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / f".{APP_NAME}"


def bootstrap_user_environment() -> Settings:
    root = application_data_dir()
    _trace(root, "bootstrap:start")
    _load_user_config(root / "config.env")
    load_credentials_into_environment()
    _trace(root, "bootstrap:configuration-loaded")
    directories = {
        "data": root / "data",
        "logs": root / "logs",
        "reports": root / "reports",
        "runs": root / "runs",
        "run": root / "run",
        "cache": root / "cache",
        "backups": root / "backups",
        "diagnostics": root / "diagnostics",
    }
    for directory in (root, *directories.values()):
        directory.mkdir(parents=True, exist_ok=True)
    _trace(root, "bootstrap:directories-ready")

    os.environ["PAT_RUNTIME_PROFILE"] = "PRODUCTION_DESKTOP"
    os.environ["PAT_DATABASE_URL"] = production_desktop_database_url(root.parent)
    os.environ.setdefault("PAT_LOG_DIR", str(directories["logs"]))
    os.environ.setdefault(
        "PAT_MARKET_DATA_PROVIDER_CACHE_DIR", str(directories["cache"] / "providers")
    )
    os.environ.setdefault(
        "PAT_DAILY_PIPELINE_REPORT_PATH", str(directories["reports"] / "DAILY_PIPELINE_REPORT.md")
    )
    os.environ.setdefault(
        "PAT_DAILY_PIPELINE_QUALITY_REPORT_PATH",
        str(directories["reports"] / "DATA_QUALITY_REPORT.md"),
    )
    os.environ.setdefault(
        "PAT_DAILY_PIPELINE_LOCK_PATH", str(directories["run"] / "daily_pipeline.lock")
    )
    os.environ.setdefault("PAT_APP_ENV", "development")

    apply_pending_restore(root, directories["data"] / "personal_alpha.db")
    _trace(root, "bootstrap:restore-checked")
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    _write_default_config(root, settings)
    _trace(root, "bootstrap:settings-ready")
    upgrade_database(settings)
    _trace(root, "bootstrap:migrations-ready")
    _verify_and_record_startup(root, settings)
    _trace(root, "bootstrap:startup-verified")
    try:
        ensure_daily_backup(
            settings,
            application_root=root,
            backup_directory=directories["backups"],
        )
    except Exception as error:  # backup failure is diagnosed but never hidden
        _trace(root, f"bootstrap:daily-backup-warning:{type(error).__name__}")
    _trace(root, "bootstrap:environment-ready")
    return settings


def process_is_running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(
                ctypes.windll.kernel32.GetExitCodeProcess(
                    process, ctypes.byref(exit_code)
                )
                and exit_code.value == 259
            )
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _verify_and_record_startup(root: Path, settings: Settings) -> None:
    free_bytes = disk_usage(root).free
    if free_bytes < MINIMUM_FREE_DISK_BYTES:
        raise OSError("At least 100 MB free disk space is required for safe startup")
    probe = root / ".write-test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    engine = build_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
            revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one_or_none()
            if not revision:
                raise RuntimeError("Database migration revision is unavailable")
            backend = connection.dialect.name
    finally:
        engine.dispose()
    status = StartupStatus(
        status="ready",
        checked_at=datetime.now(UTC).isoformat(),
        app_data_dir=str(root),
        database_backend=backend,
        bundled_runtime=bool(getattr(sys, "frozen", False)),
        free_disk_bytes=free_bytes,
        checks={
            "application_version": PRODUCT_DISPLAY_NAME,
            "app_data_writable": "ok",
            "configuration": "ok",
            "database_connection": "ok",
            "database_migration": str(revision),
            "free_disk_space": "ok",
        },
    )
    target = root / "startup-status.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(status), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def _write_default_config(root: Path, settings: Settings) -> None:
    config_path = root / "config.env"
    if config_path.exists():
        return
    config_path.write_text(
        "\n".join(
            (
                "# Personal Alpha Terminal user configuration",
                f"# {PRODUCT_DISPLAY_NAME}",
                "# PAT_ environment variables override these defaults.",
                f"PAT_DATABASE_URL={settings.database_url}",
                f"PAT_LOG_DIR={settings.log_dir}",
                f"PAT_DAILY_PIPELINE_REPORT_PATH={settings.daily_pipeline_report_path}",
                "PAT_DAILY_PIPELINE_QUALITY_REPORT_PATH="
                f"{settings.daily_pipeline_quality_report_path}",
                f"PAT_DAILY_PIPELINE_LOCK_PATH={settings.daily_pipeline_lock_path}",
                "PAT_LOG_LEVEL=INFO",
                "PAT_LLM_PROVIDER=disabled",
                "PAT_DEEPSEEK_BASE_URL=https://api.deepseek.com",
                "",
            )
        ),
        encoding="utf-8",
    )


def _load_user_config(config_path: Path) -> None:
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("PAT_"):
            os.environ.setdefault(key, value.strip())


def _trace(root: Path, message: str) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        with (root / "boot.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now(UTC).isoformat()} {message}\n")
    except OSError:
        pass

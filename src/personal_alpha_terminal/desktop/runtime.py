import json
import os
import signal
import socket
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from shutil import disk_usage
from typing import Any
from urllib.parse import urlparse

from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.core.credentials import load_credentials_into_environment
from personal_alpha_terminal.core.local_backup import apply_pending_restore, ensure_daily_backup
from personal_alpha_terminal.core.product import PRODUCT_DISPLAY_NAME
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.migrations import upgrade_database

APP_NAME = "PersonalAlphaTerminal"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8501
MINIMUM_FREE_DISK_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class InstanceInfo:
    pid: int
    executable: str
    url: str
    creation_time: int | None = None


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
    data_dir = root / "data"
    log_dir = root / "logs"
    report_dir = root / "reports"
    run_dir = root / "run"
    update_dir = root / "updates"
    backup_dir = root / "backups"
    diagnostic_dir = root / "diagnostics"
    for directory in (
        root,
        data_dir,
        log_dir,
        report_dir,
        run_dir,
        update_dir,
        backup_dir,
        diagnostic_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    _trace(root, "bootstrap:directories-ready")

    os.environ.setdefault(
        "PAT_DATABASE_URL",
        f"sqlite:///{(data_dir / 'personal_alpha.db').as_posix()}",
    )
    os.environ.setdefault("PAT_LOG_DIR", str(log_dir))
    os.environ.setdefault(
        "PAT_MARKET_DATA_PROVIDER_CACHE_DIR",
        str(root / "cache" / "providers"),
    )
    os.environ.setdefault(
        "PAT_DAILY_PIPELINE_REPORT_PATH",
        str(report_dir / "DAILY_PIPELINE_REPORT.md"),
    )
    os.environ.setdefault(
        "PAT_DAILY_PIPELINE_QUALITY_REPORT_PATH",
        str(report_dir / "DATA_QUALITY_REPORT.md"),
    )
    os.environ.setdefault(
        "PAT_DAILY_PIPELINE_LOCK_PATH",
        str(run_dir / "daily_pipeline.lock"),
    )
    # The portable SQLite desktop remains a local-development profile.  A real
    # production profile must be explicitly configured with PostgreSQL.
    os.environ.setdefault("PAT_APP_ENV", "development")
    apply_pending_restore(root, data_dir / "personal_alpha.db")
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    _trace(root, "bootstrap:settings-ready")
    _write_default_config(root, settings)
    _trace(root, "bootstrap:config-ready")
    upgrade_database(settings)
    _trace(root, "bootstrap:migration-ready")
    _verify_and_record_startup(root, settings)
    try:
        ensure_daily_backup(
            settings,
            application_root=root,
            backup_directory=backup_dir,
        )
        _trace(root, "bootstrap:daily-backup-ready")
    except Exception as error:
        _trace(root, f"bootstrap:daily-backup-warning:{type(error).__name__}")
    _trace(root, "bootstrap:environment-ready")
    return settings


def pid_file() -> Path:
    return application_data_dir() / "personal-alpha-terminal.pid"


def read_instance() -> InstanceInfo | None:
    try:
        payload = json.loads(pid_file().read_text(encoding="utf-8"))
        pid = int(payload["pid"])
        executable = str(payload["executable"])
        url = str(payload.get("url", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"))
        raw_creation_time = payload.get("creation_time")
        creation_time = int(raw_creation_time) if raw_creation_time is not None else None
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if pid <= 0 or not executable or not _is_local_dashboard_url(url):
        return None
    return InstanceInfo(
        pid=pid,
        executable=executable,
        url=url,
        creation_time=creation_time,
    )


def read_pid() -> int | None:
    instance = read_instance()
    return instance.pid if instance is not None else None


def write_instance(url: str) -> InstanceInfo:
    if not _is_local_dashboard_url(url):
        raise ValueError("desktop dashboard URL must use the local loopback address")
    info = InstanceInfo(
        pid=os.getpid(),
        executable=sys.executable,
        url=url,
        creation_time=_process_creation_time(os.getpid()),
    )
    target = pid_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(info), ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
    return info


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
                    process,
                    ctypes.byref(exit_code),
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


def process_matches_instance(instance: InstanceInfo) -> bool:
    if not process_is_running(instance.pid):
        return False
    actual_executable = _process_executable(instance.pid)
    if actual_executable is None:
        return False
    try:
        expected = os.path.normcase(str(Path(instance.executable).resolve()))
        actual = os.path.normcase(str(Path(actual_executable).resolve()))
    except OSError:
        return False
    if expected != actual:
        return False
    if instance.creation_time is None:
        return True
    return _process_creation_time(instance.pid) == instance.creation_time


def stop_running_instance() -> bool:
    instance = read_instance()
    if instance is None or not process_matches_instance(instance):
        pid_file().unlink(missing_ok=True)
        return False
    if sys.platform == "win32":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x0001, False, instance.pid)
        if not process:
            return False
        try:
            if not ctypes.windll.kernel32.TerminateProcess(process, 0):
                return False
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    else:
        os.kill(instance.pid, signal.SIGTERM)
    pid_file().unlink(missing_ok=True)
    return True


def choose_dashboard_port(
    host: str = DEFAULT_HOST,
    preferred_port: int = DEFAULT_PORT,
) -> int:
    if _port_is_available(host, preferred_port):
        return preferred_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind((host, 0))
        return int(candidate.getsockname()[1])


def stage_update() -> tuple[bool, str]:
    manifest_url = os.environ.get("PAT_UPDATE_MANIFEST_URL", "").strip()
    if not manifest_url:
        return False, "未配置 PAT_UPDATE_MANIFEST_URL，无法检查更新。"
    if urlparse(manifest_url).scheme != "https":
        return False, "更新清单必须使用 HTTPS。"
    try:
        manifest = _read_json(manifest_url)
        version = str(manifest["version"])
        package_url = str(manifest["url"])
        expected_hash = str(manifest["sha256"]).lower()
        if urlparse(package_url).scheme != "https":
            raise ValueError("update package must use HTTPS")
        destination = application_data_dir() / "updates" / f"PAT-{version}.zip"
        with urllib.request.urlopen(package_url, timeout=60) as response:
            payload = response.read()
        actual_hash = sha256(payload).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError("update SHA256 mismatch")
        destination.write_bytes(payload)
    except Exception as error:
        return False, f"更新检查失败：{error}"
    return True, f"更新包 {version} 已校验并暂存至：{destination}"


def bundled_dashboard_path() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root is not None:
        return Path(str(bundled_root)) / "personal_alpha_terminal" / "dashboard" / "app.py"
    return Path(__file__).resolve().parents[1] / "dashboard" / "app.py"


def _verify_and_record_startup(root: Path, settings: Settings) -> None:
    free_bytes = disk_usage(root).free
    if free_bytes < MINIMUM_FREE_DISK_BYTES:
        raise OSError("可用磁盘空间不足 100 MB，无法安全初始化研究数据库。")

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
                raise RuntimeError("数据库迁移版本不可用。")
            backend = connection.dialect.name
    finally:
        engine.dispose()

    checks = {
        "application_version": PRODUCT_DISPLAY_NAME,
        "app_data_writable": "ok",
        "configuration": "ok" if (root / "config.env").is_file() else "failed",
        "database_connection": "ok",
        "database_migration": str(revision),
        "free_disk_space": "ok",
    }
    if "failed" in checks.values():
        raise RuntimeError("首次启动环境检查失败。")
    status = StartupStatus(
        status="ready",
        checked_at=datetime.now(UTC).isoformat(),
        app_data_dir=str(root),
        database_backend=backend,
        bundled_runtime=bool(getattr(sys, "frozen", False)),
        free_disk_bytes=free_bytes,
        checks=checks,
    )
    (root / "startup-status.json").write_text(
        json.dumps(asdict(status), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_local_dashboard_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _process_executable(pid: int) -> str | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                process,
                0,
                buffer,
                ctypes.byref(size),
            ):
                return None
            return str(buffer.value)
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    executable = Path(f"/proc/{pid}/exe")
    try:
        return str(executable.resolve(strict=True))
    except OSError:
        return None


def _process_creation_time(pid: int) -> int | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetProcessTimes(
                process,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            return (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    try:
        return Path(f"/proc/{pid}").stat().st_ctime_ns
    except OSError:
        return None


def _read_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": PRODUCT_DISPLAY_NAME.replace(" ", "/")},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("update manifest must be a JSON object")
    return parsed


def _write_default_config(root: Path, settings: Settings) -> None:
    config_path = root / "config.env"
    if config_path.exists():
        return
    config_path.write_text(
        "\n".join(
            (
                "# Personal Alpha Terminal user configuration",
                f"# {PRODUCT_DISPLAY_NAME}",
                "# Environment variables with the PAT_ prefix override these defaults.",
                f"PAT_DATABASE_URL={settings.database_url}",
                f"PAT_LOG_DIR={settings.log_dir}",
                f"PAT_DAILY_PIPELINE_REPORT_PATH={settings.daily_pipeline_report_path}",
                (
                    "PAT_DAILY_PIPELINE_QUALITY_REPORT_PATH="
                    f"{settings.daily_pipeline_quality_report_path}"
                ),
                f"PAT_DAILY_PIPELINE_LOCK_PATH={settings.daily_pipeline_lock_path}",
                "PAT_LOG_LEVEL=INFO",
                "PAT_LLM_PROVIDER=disabled",
                "PAT_DEEPSEEK_BASE_URL=https://api.deepseek.com",
                "# PAT_UPDATE_MANIFEST_URL=https://example.com/pat/latest.json",
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
            stream.write(f"{message}\n")
    except OSError:
        pass

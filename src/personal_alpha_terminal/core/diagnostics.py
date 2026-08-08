from __future__ import annotations

import json
import platform
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import disk_usage

from sqlalchemy import text

from personal_alpha_terminal.agents.llm.factory import build_llm_provider
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.product import PRODUCT_DISPLAY_NAME
from personal_alpha_terminal.data.database import build_engine

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token|password|secret)\s*[:=]\s*([^\s,;]+)"
)
PRIVATE_AMOUNT_PATTERN = re.compile(
    r"(?i)(portfolio[_-]?value|position[_-]?value|market[_-]?value|"
    r"position[_-]?amount|holding[_-]?amount|quantity)\s*[:=]\s*([^\s,;]+)"
)


@dataclass(frozen=True, slots=True)
class DiagnosticSummary:
    application: str
    python_version: str
    bundled_runtime: bool
    database_status: str
    database_backend: str
    ai_provider_status: str
    data_directory: str
    log_directory: str
    configuration_path: str
    free_disk_bytes: int
    latest_error: str | None
    checked_at: str


def collect_diagnostics(settings: Settings, *, application_root: Path) -> DiagnosticSummary:
    engine = build_engine(settings.database_url)
    database_status = "unavailable"
    backend = "unknown"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            backend = connection.dialect.name
            database_status = "ready"
    except Exception:
        database_status = "error"
    finally:
        engine.dispose()
    provider = build_llm_provider(settings)
    if provider.name == "disabled":
        provider_status = "未配置，可在设置中启用"
    elif provider.name == "mock":
        provider_status = "Mock（明确标识，不调用外部服务）"
    else:
        provider_status = f"{provider.name} · configured"
    return DiagnosticSummary(
        application=PRODUCT_DISPLAY_NAME,
        python_version=platform.python_version(),
        bundled_runtime=bool(getattr(sys, "frozen", False)),
        database_status=database_status,
        database_backend=backend,
        ai_provider_status=provider_status,
        data_directory=str(application_root / "data"),
        log_directory=str(settings.log_dir),
        configuration_path=str(application_root / "config.env"),
        free_disk_bytes=disk_usage(application_root).free,
        latest_error=_latest_error(settings.log_dir),
        checked_at=datetime.now(UTC).isoformat(),
    )


def create_diagnostic_bundle(
    settings: Settings,
    *,
    application_root: Path,
    output_directory: Path,
) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = output_directory / f"PAT-diagnostics-{stamp}.zip"
    with tempfile.TemporaryDirectory(prefix="pat-diagnostics-", dir=output_directory) as raw:
        staging = Path(raw)
        summary = collect_diagnostics(settings, application_root=application_root)
        (staging / "diagnostics.json").write_text(
            json.dumps(asdict(summary), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for name in ("startup-status.json", "user-preferences.json"):
            source = application_root / name
            if source.is_file():
                shutil.copy2(source, staging / name)
        config = application_root / "config.env"
        if config.is_file():
            (staging / "config.redacted.env").write_text(
                redact_text(config.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
        logs = staging / "logs"
        logs.mkdir()
        for source in sorted(settings.log_dir.glob("*.log*"))[-5:]:
            if source.is_file():
                content = source.read_text(encoding="utf-8", errors="replace")[-200_000:]
                (logs / source.name).write_text(redact_text(content), encoding="utf-8")
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(staging))
    return destination


def redact_text(content: str) -> str:
    redacted = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", content)
    return PRIVATE_AMOUNT_PATTERN.sub(
        lambda match: f"{match.group(1)}=<redacted>",
        redacted,
    )


def _latest_error(log_directory: Path) -> str | None:
    log = log_directory / "personal-alpha-terminal.log"
    if not log.is_file():
        return None
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-1000:]):
        if " | ERROR | " in line or " | CRITICAL | " in line:
            return redact_text(line)[-500:]
    return None

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from sqlalchemy.engine import make_url

from personal_alpha_terminal.core.config import Settings


class RuntimeProfile(StrEnum):
    PRODUCTION_DESKTOP = "PRODUCTION_DESKTOP"
    DEVELOPMENT = "DEVELOPMENT"
    TEST = "TEST"


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Single authoritative runtime binding for one application process."""

    profile: RuntimeProfile
    database_url: str
    database_path: Path | None
    application_root: Path
    split_brain_candidates: tuple[Path, ...]

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        project_root: Path | None = None,
        local_app_data: Path | None = None,
    ) -> RuntimeContext:
        root = (project_root or Path.cwd()).resolve()
        configured_url = make_url(settings.database_url)
        isolated_memory = (
            configured_url.get_backend_name() == "sqlite"
            and configured_url.database in {None, "", ":memory:"}
        )
        profile = (
            RuntimeProfile.TEST
            if isolated_memory
            else RuntimeProfile(settings.runtime_profile)
        )
        desktop_root = (
            local_app_data
            or Path(os.environ.get("LOCALAPPDATA", Path.home()))
        ).resolve() / "PersonalAlphaTerminal"
        if profile is RuntimeProfile.PRODUCTION_DESKTOP:
            application_root = desktop_root
            expected_path = (desktop_root / "data" / "personal_alpha.db").resolve()
            database_url = f"sqlite:///{expected_path.as_posix()}"
        elif profile is RuntimeProfile.DEVELOPMENT:
            application_root = root
            expected_path = (root / "var" / "personal_alpha.db").resolve()
            configured = make_url(settings.database_url)
            if configured.get_backend_name() == "sqlite" and configured.database:
                candidate = Path(configured.database)
                expected_path = (
                    candidate if candidate.is_absolute() else root / candidate
                ).resolve()
                database_url = f"sqlite:///{expected_path.as_posix()}"
            else:
                database_url = settings.database_url
                expected_path = None
        else:
            application_root = root
            configured = configured_url
            if isolated_memory:
                return cls(profile, "sqlite://", None, application_root, ())
            if configured.get_backend_name() != "sqlite" or not configured.database:
                raise ValueError("TEST profile requires an explicit SQLite database path")
            candidate = Path(configured.database)
            if not candidate.is_absolute():
                candidate = root / candidate
            expected_path = candidate.resolve()
            database_url = f"sqlite:///{expected_path.as_posix()}"
            if expected_path == (root / "var" / "personal_alpha.db").resolve():
                raise ValueError("TEST profile cannot bind the shared development database")
            if expected_path == (desktop_root / "data" / "personal_alpha.db").resolve():
                raise ValueError("TEST profile cannot bind the desktop database")

        candidates = tuple(
            path
            for path in (
                (root / "var" / "personal_alpha.db").resolve(),
                (desktop_root / "data" / "personal_alpha.db").resolve(),
            )
            if _safe_exists(path) and path != expected_path
        )
        return cls(profile, database_url, expected_path, application_root, candidates)

    @property
    def database_fingerprint(self) -> str:
        if self.database_path is None or not self.database_path.exists():
            return "uninitialized"
        digest = sha256()
        with self.database_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def assert_same_database(self, database_url: str) -> None:
        candidate = make_url(database_url)
        authoritative = make_url(self.database_url)
        if candidate.render_as_string(hide_password=False) != authoritative.render_as_string(
            hide_password=False
        ):
            raise RuntimeError(
                "database split-brain prevented: process is already bound to "
                f"{self.database_url!r}, not {database_url!r}"
            )


def production_desktop_database_url(local_app_data: Path | None = None) -> str:
    base = (local_app_data or Path(os.environ.get("LOCALAPPDATA", Path.home()))).resolve()
    path = base / "PersonalAlphaTerminal" / "data" / "personal_alpha.db"
    return f"sqlite:///{path.as_posix()}"


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False

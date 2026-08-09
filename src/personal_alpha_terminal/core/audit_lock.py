from __future__ import annotations

import json
import os
import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import TracebackType

_CONTROLLED_ROOTS = ("src", "migrations", "scripts", "tests")
_CONTROLLED_FILES = (
    "alembic.ini",
    "config.yaml",
    "main.py",
    "pyproject.toml",
    "sitecustomize.py",
)
_IGNORED = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def production_source_hash(root: Path) -> str:
    resolved = root.resolve()
    files = [resolved / name for name in _CONTROLLED_FILES if (resolved / name).is_file()]
    for name in _CONTROLLED_ROOTS:
        base = resolved / name
        if base.exists():
            files.extend(
                item
                for item in base.rglob("*")
                if item.is_file() and not any(part in _IGNORED for part in item.parts)
            )
    digest = sha256()
    for path in sorted(set(files), key=lambda item: item.relative_to(resolved).as_posix()):
        digest.update(path.relative_to(resolved).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class AuditBuildLock(AbstractContextManager["AuditBuildLock"]):
    """Exclusive validation lock that also detects production-source drift."""

    def __init__(self, root: Path, *, purpose: str) -> None:
        self.root = root.resolve()
        self.path = self.root / ".audit-lock"
        self.purpose = purpose
        self.token = uuid.uuid4().hex
        self.initial_hash = ""

    def __enter__(self) -> AuditBuildLock:
        self.initial_hash = production_source_hash(self.root)
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise RuntimeError(f"audit/build validation is already running: {self.path}") from error
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "token": self.token,
                    "pid": os.getpid(),
                    "purpose": self.purpose,
                    "started_at": datetime.now(UTC).isoformat(),
                    "source_hash": self.initial_hash,
                },
                stream,
                sort_keys=True,
            )
        return self

    def verify_unchanged(self) -> None:
        current = production_source_hash(self.root)
        if current != self.initial_hash:
            raise RuntimeError(
                "production source hash drifted during validation; results are invalid"
            )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                self.verify_unchanged()
        finally:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                payload = {}
            if payload.get("token") == self.token and not self.path.is_symlink():
                self.path.unlink(missing_ok=True)

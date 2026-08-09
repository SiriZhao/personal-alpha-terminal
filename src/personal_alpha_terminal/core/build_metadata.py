from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from personal_alpha_terminal import __build_version__, __version__
from personal_alpha_terminal.core.fingerprints import fingerprint


@dataclass(frozen=True, slots=True)
class BuildMetadata:
    version: str
    build_id: str
    git_commit: str
    build_time: str
    dependency_lock_hash: str


def current_build_metadata(project_root: Path | None = None) -> BuildMetadata:
    embedded = Path(__file__).with_name("build_metadata.json")
    if embedded.exists():
        payload = json.loads(embedded.read_text(encoding="utf-8"))
        return BuildMetadata(**payload)
    root = project_root or Path.cwd()
    commit = os.environ.get("PAT_BUILD_GIT_COMMIT") or _source_commit(root)
    lock = root / "pyproject.toml"
    lock_hash = fingerprint(lock.read_text(encoding="utf-8")) if lock.exists() else "UNAVAILABLE"
    return BuildMetadata(
        version=__version__,
        build_id=__build_version__,
        git_commit=commit,
        build_time="SOURCE_RUNTIME",
        dependency_lock_hash=lock_hash,
    )


def _source_commit(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNAVAILABLE"
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and len(value) == 40 else "UNAVAILABLE"

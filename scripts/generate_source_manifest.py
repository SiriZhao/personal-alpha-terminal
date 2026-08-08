"""Generate a deterministic SHA256 manifest for production-controlled files."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


INCLUDED_ROOT_FILES = {
    ".env.example",
    ".env.production.example",
    ".gitignore",
    "alembic.ini",
    "CHANGELOG.md",
    "config.yaml",
    "main.py",
    "pyproject.toml",
    "README.md",
    "run_terminal.bat",
    "sitecustomize.py",
}
INCLUDED_DIRECTORIES = ("src", "migrations", "scripts", "tests")
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def controlled_files(root: Path) -> list[Path]:
    files = [root / name for name in sorted(INCLUDED_ROOT_FILES) if (root / name).is_file()]
    for directory in INCLUDED_DIRECTORIES:
        base = root / directory
        if not base.exists():
            continue
        files.extend(
            path
            for path in base.rglob("*")
            if path.is_file() and not any(part in IGNORED_PARTS for part in path.parts)
        )
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_manifest(root: Path) -> str:
    lines = ["# SHA256  PATH", ""]
    for path in controlled_files(root):
        lines.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="docs/development/baseline/PRODUCTION_SOURCE_SHA256.txt",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = (root / args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = render_manifest(root)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(destination)
    print(f"wrote {destination} ({len(payload.splitlines()) - 2} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

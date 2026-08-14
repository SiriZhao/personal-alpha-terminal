from __future__ import annotations

import ast
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

_INCLUDED_DIRECTORIES = ("src", "migrations", "scripts", "packaging", "tests")
_INCLUDED_ROOT_FILES = (
    "alembic.ini",
    "config.example.yaml",
    "config.yaml",
    "pyproject.toml",
    "README.md",
)
_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    ".venv",
    "__pycache__",
    "build",
    "node_modules",
    "release",
    "source_audit_export",
    "var",
}


@dataclass(frozen=True, slots=True)
class SourceAuditExport:
    destination: Path
    file_count: int
    production_file_count: int
    manifest_path: Path
    manifest_hash: str


def export_source_audit(project_root: Path, destination: Path) -> SourceAuditExport:
    """Export reviewable source while retaining package-local ``reports`` code.

    Root runtime output directories are outside the explicit include list. A
    directory named ``reports`` inside ``src/personal_alpha_terminal`` is
    production code and is deliberately never filtered by name.
    """

    root = project_root.resolve()
    output = destination.resolve()
    if output == root or root in output.parents and output.name not in {
        "source_audit_export",
        "audit-export",
    }:
        raise ValueError("audit destination inside project must use an audit-export name")
    files = _collect_source_files(root)
    for source in files:
        relative = source.relative_to(root)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    _validate_internal_imports(output)
    entries = [
        {
            "path": source.relative_to(root).as_posix(),
            "sha256": _sha256(source),
            "size": source.stat().st_size,
        }
        for source in files
    ]
    production_file_count = sum(
        1
        for source in files
        if source.relative_to(root).as_posix().startswith("src/personal_alpha_terminal/")
    )
    manifest = {
        "schema_version": "source-audit-export-v1",
        "files": entries,
        "production_file_count": production_file_count,
    }
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    manifest_path = output / "SOURCE_AUDIT_MANIFEST.json"
    manifest_path.write_text(text, encoding="utf-8")
    return SourceAuditExport(
        destination=output,
        file_count=len(entries),
        production_file_count=production_file_count,
        manifest_path=manifest_path,
        manifest_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _collect_source_files(root: Path) -> tuple[Path, ...]:
    files: set[Path] = set()
    for name in _INCLUDED_DIRECTORIES:
        directory = root / name
        if not directory.is_dir():
            continue
        for candidate in directory.rglob("*"):
            relative = candidate.relative_to(root)
            if candidate.is_file() and not any(part in _EXCLUDED_PARTS for part in relative.parts):
                files.add(candidate)
    for name in _INCLUDED_ROOT_FILES:
        candidate = root / name
        if candidate.is_file():
            files.add(candidate)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _validate_internal_imports(export_root: Path) -> None:
    source_root = export_root / "src"
    package_root = source_root / "personal_alpha_terminal"
    if not package_root.is_dir():
        raise ValueError("audit export is missing the production package")
    missing: set[str] = set()
    for source in package_root.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = (node.module,)
            for module in modules:
                if not module.startswith("personal_alpha_terminal"):
                    continue
                relative = Path(*module.split("."))
                if not (source_root / relative).with_suffix(".py").exists() and not (
                    source_root / relative / "__init__.py"
                ).exists():
                    missing.add(module)
    if missing:
        raise ValueError(
            "audit export misses imported production modules: "
            + ", ".join(sorted(missing))
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

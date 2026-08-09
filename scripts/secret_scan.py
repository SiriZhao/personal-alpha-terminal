from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

_TOKEN_PATTERNS = (
    re.compile(r"\bsk-(?:proj|svcacct)-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{20,}"),
)
_SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    ".venv",
    ".venv314",
    "__pycache__",
    "build",
    "release",
    "var",
}


def _candidate_paths(root: Path, *, use_git: bool) -> list[Path]:
    if not use_git:
        return [path for path in root.rglob("*") if path.is_file()]
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [
        root / Path(raw.decode("utf-8", errors="surrogateescape"))
        for raw in completed.stdout.split(b"\0")
        if raw
    ]


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Scan source or a release tree for credential patterns."
    )
    parser.add_argument("--root", type=Path, default=project_root)
    args = parser.parse_args()
    root = args.root.resolve()
    use_git = root == project_root
    findings: list[str] = []
    for path in _candidate_paths(root, use_git=use_git):
        relative = path.relative_to(root)
        if any(part in _SKIP_PARTS for part in relative.parts):
            continue
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in _TOKEN_PATTERNS):
                findings.append(f"{relative.as_posix()}:{number}")
    if findings:
        print("SECRET_SCAN_FAIL")
        for finding in findings:
            print(f"POTENTIAL_SECRET={finding}")
        return 1
    print("SECRET_SCAN_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

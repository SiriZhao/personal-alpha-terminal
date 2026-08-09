from pathlib import Path

import pytest

from personal_alpha_terminal.core.source_audit import export_source_audit


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_export_keeps_package_reports_but_excludes_root_runtime_reports(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    _write(root / "pyproject.toml", "[project]\nname='audit-fixture'\n")
    _write(root / "src/personal_alpha_terminal/__init__.py")
    _write(root / "src/personal_alpha_terminal/reports/__init__.py")
    _write(root / "src/personal_alpha_terminal/reports/service.py", "VALUE = 1\n")
    _write(
        root / "src/personal_alpha_terminal/app.py",
        "from personal_alpha_terminal.reports.service import VALUE\n",
    )
    _write(root / "reports/runtime-output.json", "{}\n")

    result = export_source_audit(root, tmp_path / "audit-export")

    assert (result.destination / "src/personal_alpha_terminal/reports/service.py").exists()
    assert not (result.destination / "reports/runtime-output.json").exists()
    assert result.production_file_count == 4


def test_export_fails_when_an_internal_import_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write(root / "src/personal_alpha_terminal/__init__.py")
    _write(
        root / "src/personal_alpha_terminal/app.py",
        "from personal_alpha_terminal.missing.service import VALUE\n",
    )

    with pytest.raises(ValueError, match="misses imported production modules"):
        export_source_audit(root, tmp_path / "audit-export")

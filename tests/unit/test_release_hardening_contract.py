from pathlib import Path


def test_release_build_embeds_provenance_and_excludes_private_runtime_data() -> None:
    root = Path(__file__).resolve().parents[2]
    build = (root / "packaging/build_terminal_release.ps1").read_text(encoding="utf-8")
    spec = (root / "packaging/personal-alpha-terminal-console.spec").read_text(
        encoding="utf-8"
    )
    smoke = (root / "packaging/test_terminal_release.ps1").read_text(encoding="utf-8")

    assert "Tracked production tree is dirty" in build
    assert "BUILD_MANIFEST.json" in build
    assert "SHA256SUMS.txt" in build
    assert "GetRelativePath" not in build
    assert "Release file escaped product root" in build
    for forbidden in (".git", "tests", ".env", "personal_alpha.db"):
        assert f'"{forbidden}"' in build
    assert "build_metadata.json" in spec
    assert '"streamlit"' in spec and '"textual"' in spec
    assert "ForbiddenProcesses" in smoke
    assert "PersonalAlphaTerminal.exe" in smoke

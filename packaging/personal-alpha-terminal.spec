from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

project_root = Path(SPECPATH).resolve().parent
streamlit_datas, streamlit_binaries, streamlit_hidden = collect_all("streamlit")
plotly_datas, plotly_binaries, plotly_hidden = collect_all("plotly")

analysis = Analysis(
    [str(project_root / "src" / "personal_alpha_terminal" / "desktop" / "launcher.py")],
    pathex=[str(project_root / "src")],
    binaries=streamlit_binaries + plotly_binaries,
    datas=[
        *streamlit_datas,
        *plotly_datas,
        (
            str(project_root / "src" / "personal_alpha_terminal" / "dashboard"),
            "personal_alpha_terminal/dashboard",
        ),
        (str(project_root / "migrations"), "migrations"),
        (str(project_root / "alembic.ini"), "."),
        (str(project_root / ".streamlit"), ".streamlit"),
    ],
    hiddenimports=[
        *streamlit_hidden,
        *plotly_hidden,
        *collect_submodules("personal_alpha_terminal"),
        "sqlalchemy.dialects.sqlite",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "notebook"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PersonalAlphaTerminal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=str(project_root / "packaging" / "version_info.txt"),
)
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="PersonalAlphaTerminal",
)

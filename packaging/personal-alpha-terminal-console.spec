from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

project_root = Path.cwd()
yfinance_datas, yfinance_binaries, yfinance_hidden = collect_all("yfinance")

analysis = Analysis(
    [str(project_root / "src" / "personal_alpha_terminal" / "console.py")],
    pathex=[str(project_root / "src")],
    binaries=yfinance_binaries,
    datas=[
        *yfinance_datas,
        *collect_data_files("exchange_calendars"),
        (str(project_root / "migrations"), "migrations"),
        (str(project_root / "alembic.ini"), "."),
        (
            str(project_root / "packaging" / "build_metadata.json"),
            "personal_alpha_terminal/core",
        ),
    ],
    hiddenimports=[
        *yfinance_hidden,
        *collect_submodules("personal_alpha_terminal.models"),
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "exchange_calendars.exchange_calendar_xnys",
        "sklearn.covariance",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "akshare",
        "altair",
        "backtrader",
        "IPython",
        "jedi",
        "llvmlite",
        "matplotlib",
        "mypy",
        "numba",
        "notebook",
        "plotly",
        "polars",
        "polars_st",
        "_polars_runtime_32",
        "pyarrow",
        "psygnal",
        "coverage",
        "qlib",
        "streamlit",
        "textual",
        "vectorbt",
    ],
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
    console=True,
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

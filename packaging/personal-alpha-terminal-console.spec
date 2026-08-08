from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

project_root = Path.cwd()
textual_datas, textual_binaries, textual_hidden = collect_all("textual")
yfinance_datas, yfinance_binaries, yfinance_hidden = collect_all("yfinance")

analysis = Analysis(
    [str(project_root / "src" / "personal_alpha_terminal" / "console.py")],
    pathex=[str(project_root / "src")],
    binaries=[*textual_binaries, *yfinance_binaries],
    datas=[
        *textual_datas,
        *yfinance_datas,
        *collect_data_files("exchange_calendars"),
        (str(project_root / "migrations"), "migrations"),
        (str(project_root / "alembic.ini"), "."),
    ],
    hiddenimports=[
        *textual_hidden,
        *yfinance_hidden,
        *collect_submodules("personal_alpha_terminal.models"),
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "exchange_calendars.exchange_calendar_xnys",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "akshare",
        "backtrader",
        "matplotlib",
        "notebook",
        "plotly",
        "qlib",
        "sklearn",
        "streamlit",
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
    name="QuantTerminal",
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
    name="QuantTerminal",
)

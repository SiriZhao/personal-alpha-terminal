"""ROUND22.1 terminal startup/progress hotfix tests."""
from __future__ import annotations

import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

from rich.console import Console
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.market_data.repository import PriceRepository
from personal_alpha_terminal.data.market_data.service import MarketDataEngine
from personal_alpha_terminal.models import Base, Stock
from personal_alpha_terminal.terminal import cli as cli_module
from personal_alpha_terminal.terminal.cli import (
    _progress_printer,
    _startup_panel,
    build_parser,
)


def _config(tmp_path: Path) -> EffectiveRuntimeConfig:
    return EffectiveRuntimeConfig(
        report_dir=tmp_path / "reports",
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'empty.db'}"),
    )


def test_startup_panel_prints_immediately_without_network(monkeypatch, tmp_path: Path) -> None:
    output = io.StringIO()
    monkeypatch.setattr(cli_module, "console", Console(file=output))
    _startup_panel(_config(tmp_path), refresh=True)
    rendered = output.getvalue()
    assert "PERSONAL ALPHA TERMINAL" in rendered
    assert "REFRESHING" in rendered


def test_startup_panel_no_refresh_marks_cache_replay(monkeypatch, tmp_path: Path) -> None:
    output = io.StringIO()
    monkeypatch.setattr(cli_module, "console", Console(file=output))
    _startup_panel(_config(tmp_path), refresh=False)
    assert "CACHE_REPLAY" in output.getvalue()


def test_progress_printer_flushes_and_writes_heartbeat(monkeypatch, tmp_path: Path) -> None:
    output = io.StringIO()
    monkeypatch.setattr(cli_module, "console", Console(file=output))
    notify = _progress_printer(_config(tmp_path))
    notify("[Provider] ?? 2 / 4")
    assert "?? 2 / 4" in output.getvalue()
    heartbeat = (
        tmp_path
        / "reports"
        / ".."
        / "var"
        / "logs"
        / "terminal-heartbeat.json"
    ).resolve()
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert payload["current_stage"].startswith("[Provider]")
    assert payload["processed"] == 2
    assert payload["total"] == 4


def test_batch_refresh_reports_provider_progress(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)

    class _Batch:
        source = "yahoo_finance"
        provider_id = "yahoo_finance.broad_universe_batch"
        chunk_size = 100

        def download(self, symbols, *, start_date, end_date):
            del symbols, start_date, end_date
            return type(
                "Report",
                (),
                {"received_symbols": (), "failed_symbols": (), "bars": ()},
            )()

    available = datetime(2026, 8, 3, 20, 30, tzinfo=UTC)
    with Session(engine) as session:
        stock = Stock(
            canonical_code="US:XNAS:PROG",
            symbol="PROG",
            name="Progress",
            market="US",
            exchange="XNAS",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
            list_date=date(2020, 1, 1),
            is_active=True,
            source="fixture",
            provider="fixture",
            available_time=available,
            ingested_time=available,
        )
        session.add(stock)
        session.flush()
        service = MarketDataEngine(
            providers=[],
            repository=PriceRepository(session),
            settings=Settings(
                market_data_max_retries=0,
                market_data_retry_backoff_seconds=0.0,
                market_data_provider_cache_dir=tmp_path / "cache",
                market_data_timeout_seconds=10,
                market_data_default_start=date(2026, 8, 1),
                market_data_overlap_days=2,
            ),
            batch_provider=_Batch(),
            batch_threshold=1,
        )
        progress: list[str] = []
        service._run_batch_refresh(
            [stock],
            date(2026, 8, 3),
            forced_start_date=date(2026, 8, 1),
            progress=progress.append,
        )
    assert any("[Provider]" in item and "1 / 1" in item for item in progress)
    assert any("0 / 1" in item for item in progress)
    engine.dispose()


def test_terminal_status_command_is_registered() -> None:
    args = build_parser().parse_args(["terminal-status", "--json"])
    assert args.command == "terminal-status"
    assert args.json is True


def test_run_terminal_bat_uses_unbuffered_python(tmp_path: Path) -> None:
    bat = Path("run_terminal.bat")
    content = bat.read_text(encoding="utf-8")
    assert 'python.exe" -u main.py' in content or "python -u main.py" in content
    assert "PYTHONUNBUFFERED=1" in content

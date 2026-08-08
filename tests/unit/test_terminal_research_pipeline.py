from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from rich.console import Console

from personal_alpha_terminal.terminal import cli as terminal_cli
from personal_alpha_terminal.terminal.config import TerminalConfig, load_config
from personal_alpha_terminal.terminal.pipeline import DailyResearchPipeline
from personal_alpha_terminal.terminal.providers import ProviderError, ProviderResult


def _frame(start: str = "2024-01-02", periods: int = 260) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    close = pd.Series(range(100, 100 + periods), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "adjusted_close": close,
            "volume": 1_000_000,
        }
    )


class _Provider:
    name = "fixture"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def fetch_daily(self, symbol: str, start: date, end: date) -> ProviderResult:
        if self.fail:
            raise ProviderError("network unavailable")
        frame = _frame()
        return ProviderResult(
            symbol=symbol,
            frame=frame,
            provider=self.name,
            endpoint="fixture://daily",
            requested_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            adjustment_policy="raw_fixture;corporate_actions_certified",
            content_hash=hashlib.sha256(symbol.encode()).hexdigest(),
        )


def _config(tmp_path: Path) -> TerminalConfig:
    return TerminalConfig(
        symbols=("AAPL", "MSFT", "NVDA"),
        benchmark="SPY",
        nasdaq_benchmark="QQQ",
        vix_symbol="^VIX",
        history_start="2024-01-02",
        cache_dir=tmp_path / "cache",
        report_dir=tmp_path / "reports",
        required_symbols=("SPY", "QQQ", "^VIX"),
        holdings={"AAPL": 0.3, "MSFT": 0.3},
    )


def test_pipeline_uses_real_provider_contract_and_writes_cache(tmp_path: Path) -> None:
    pipeline = DailyResearchPipeline(_config(tmp_path), primary=_Provider(), fallback=_Provider())
    result = pipeline.run(as_of=date(2024, 12, 31))
    assert result.data_quality.status == "PASSED"
    assert result.model_status == "INSUFFICIENT_DATA"
    assert not result.signals
    assert any("PRODUCTION_APPROVED" in warning for warning in result.warnings)
    assert (tmp_path / "cache" / "AAPL_daily.parquet").exists()
    assert (tmp_path / "cache" / "AAPL_daily.manifest.json").exists()


def test_pipeline_falls_back_to_cached_data_when_network_fails(tmp_path: Path) -> None:
    config = _config(tmp_path)
    DailyResearchPipeline(
        config, primary=_Provider(), fallback=_Provider()
    ).run(as_of=date(2024, 12, 31))
    result = DailyResearchPipeline(
        config,
        primary=_Provider(fail=True),
        fallback=_Provider(fail=True),
    ).run(as_of=date(2024, 12, 31))
    assert result.data_quality.status == "PASSED"
    assert any("已使用缓存" in warning for warning in result.warnings)


def test_empty_cache_and_provider_failure_is_blocked(tmp_path: Path) -> None:
    pipeline = DailyResearchPipeline(
        _config(tmp_path),
        primary=_Provider(fail=True),
        fallback=_Provider(fail=True),
    )
    result = pipeline.run(as_of=date(2024, 12, 31))
    assert result.data_quality.status == "BLOCKED"
    assert result.model_status == "INSUFFICIENT_DATA"
    assert not result.signals


def test_config_rejects_unsupported_indented_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("market: US\ninvalid:\n  nested: no\n", encoding="utf-8")
    try:
        load_config(path)
    except ValueError as error:
        assert "configuration" in str(error) or "empty value" in str(error)
    else:  # pragma: no cover
        raise AssertionError("invalid configuration must fail loudly")


def test_today_attaches_only_persisted_decision_and_keeps_manual_execution_wait(
    tmp_path: Path,
    monkeypatch,
) -> None:
    analysis = DailyResearchPipeline(
        _config(tmp_path), primary=_Provider(), fallback=_Provider()
    ).run(as_of=date(2024, 12, 31))
    candidate = SimpleNamespace(
        ticker="AAPL",
        action="BUY",
        confidence_score=Decimal("80"),
        current_weight=Decimal("0.05"),
        target_weight=Decimal("0.10"),
        rationale=("production alpha",),
        risk_factors=("equity risk",),
        executable=True,
    )
    service = SimpleNamespace(get_action_candidates=lambda: (candidate,))
    monkeypatch.setattr(terminal_cli, "_application_service", lambda: service)

    result = terminal_cli._attach_authorized_candidates(analysis)

    assert result.actions[0].action == "BUY"
    assert result.actions[0].suggested_change == pytest.approx(0.05)
    assert result.actions[0].execution_feasibility == "WAIT"
    assert result.actions[0].estimated_cost_rate is None


def test_daily_cli_consumes_only_application_daily_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result = SimpleNamespace(actionable=True)
    service = SimpleNamespace(
        run_daily_quant_report=lambda **_kwargs: result,
    )
    monkeypatch.setattr(terminal_cli, "load_config", lambda _path: _config(tmp_path))
    monkeypatch.setattr(
        terminal_cli,
        "_application_service",
        lambda **_kwargs: service,
    )
    rendered: list[object] = []
    monkeypatch.setattr(
        terminal_cli,
        "render_daily_quant_result",
        lambda value, _console: rendered.append(value),
    )

    exit_code = terminal_cli.run_daily(tmp_path / "config.yaml", wait=False)

    assert exit_code == 0
    assert rendered == [result]


def test_daily_redirected_tty_eof_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    result = SimpleNamespace(actionable=True)
    service = SimpleNamespace(run_daily_quant_report=lambda **_kwargs: result)
    monkeypatch.setattr(terminal_cli, "load_config", lambda _path: _config(tmp_path))
    monkeypatch.setattr(
        terminal_cli,
        "_application_service",
        lambda **_kwargs: service,
    )
    monkeypatch.setattr(
        terminal_cli, "render_daily_quant_result", lambda _result, _console: None
    )
    monkeypatch.setattr(terminal_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        terminal_cli.console,
        "input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError),
    )

    assert terminal_cli.run_daily(tmp_path / "config.yaml", wait=True) == 0


def test_doctor_reads_real_portfolio_ledger_not_legacy_config(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(tmp_path)
    session = SimpleNamespace(
        timestamp_et=datetime(2026, 8, 8, tzinfo=UTC),
        session=SimpleNamespace(value="CLOSED"),
        trade_date=date(2026, 8, 10),
    )
    pipeline = SimpleNamespace(
        market_data=SimpleNamespace(
            providers=(SimpleNamespace(name="yahoo"), SimpleNamespace(name="stooq")),
            calendar=SimpleNamespace(classify=lambda _now: session),
        )
    )
    application = SimpleNamespace(
        get_system_health=lambda: SimpleNamespace(
            database=SimpleNamespace(code="READY", title_zh="数据库正常")
        ),
        list_portfolios=lambda: (
            {
                "id": 1,
                "name": "Release Smoke",
                "base_currency": "USD",
                "cash_balance": 100_000.0,
            },
        ),
    )
    output = Console(record=True, width=180)
    monkeypatch.setattr(terminal_cli, "load_config", lambda _path: config)
    monkeypatch.setattr(terminal_cli, "DailyResearchPipeline", lambda _config: pipeline)
    monkeypatch.setattr(terminal_cli, "_application_service", lambda: application)
    monkeypatch.setattr(terminal_cli, "console", output)

    assert terminal_cli._doctor(tmp_path / "config.yaml") == 0
    rendered = output.export_text()
    assert "Release Smoke" in rendered
    assert "real portfolio ledger" in rendered


def test_decision_database_error_is_redacted_from_today(tmp_path: Path, monkeypatch) -> None:
    analysis = DailyResearchPipeline(
        _config(tmp_path), primary=_Provider(), fallback=_Provider()
    ).run(as_of=date(2024, 12, 31))

    def fail_service() -> None:
        raise RuntimeError("sensitive SQL and local path")

    monkeypatch.setattr(terminal_cli, "_application_service", fail_service)

    result = terminal_cli._attach_authorized_candidates(analysis)

    assert "RuntimeError" in result.warnings[-1]
    assert "sensitive SQL" not in result.warnings[-1]

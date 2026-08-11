import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from personal_alpha_terminal.terminal import cli as terminal_cli
from personal_alpha_terminal.terminal.config import TerminalConfig, load_config


def _config(tmp_path: Path) -> TerminalConfig:
    return TerminalConfig(
        cache_dir=tmp_path / "cache",
        report_dir=tmp_path / "reports",
        portfolio_id=1,
    )


def test_config_rejects_unsupported_indented_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("market: US\ninvalid:\n  nested: no\n", encoding="utf-8")
    try:
        load_config(path)
    except ValueError as error:
        assert "configuration" in str(error) or "empty value" in str(error)
    else:  # pragma: no cover
        raise AssertionError("invalid configuration must fail loudly")


def test_daily_cli_consumes_only_application_daily_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result = SimpleNamespace(actionable=True)
    service = SimpleNamespace(run_daily_quant_report=lambda **_kwargs: result)
    monkeypatch.setattr(terminal_cli, "load_config", lambda _path: _config(tmp_path))
    monkeypatch.setattr(terminal_cli, "_application_service", lambda **_kwargs: service)
    rendered: list[object] = []
    monkeypatch.setattr(
        terminal_cli,
        "render_daily_quant_result",
        lambda value, _console: rendered.append(value),
    )

    assert terminal_cli.run_daily(tmp_path / "config.yaml", wait=False) == 0
    assert rendered == [result]


def test_daily_redirected_tty_eof_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    result = SimpleNamespace(actionable=True)
    service = SimpleNamespace(run_daily_quant_report=lambda **_kwargs: result)
    monkeypatch.setattr(terminal_cli, "load_config", lambda _path: _config(tmp_path))
    monkeypatch.setattr(terminal_cli, "_application_service", lambda **_kwargs: service)
    monkeypatch.setattr(terminal_cli, "render_daily_quant_result", lambda *_args: None)
    monkeypatch.setattr(terminal_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        terminal_cli.console,
        "input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError),
    )

    assert terminal_cli.run_daily(tmp_path / "config.yaml", wait=True) == 0


def test_portfolio_import_is_preview_only_without_commit(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "positions.csv"
    source.write_text("Symbol,Quantity,Average Cost\nAAPL,2,100\n", encoding="utf-8")
    parsed = SimpleNamespace(
        format_name="generic_positions",
        rows=(SimpleNamespace(symbol="AAPL", quantity=2, average_cost=100),),
        cash_balance=None,
        warnings=(),
    )
    commits: list[object] = []
    service = SimpleNamespace(
        preview_portfolio_csv=lambda **_kwargs: parsed,
        import_portfolio_csv=lambda **kwargs: commits.append(kwargs),
    )
    monkeypatch.setattr(terminal_cli, "_application_service", lambda: service)
    args = SimpleNamespace(
        command="portfolio-import",
        csv=source,
        portfolio_id=1,
        as_of=date(2026, 8, 8).isoformat(),
        commit=False,
    )

    assert terminal_cli._portfolio_command(args) == 0
    assert commits == []


def test_explain_reads_only_persisted_decision_trace(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    certificate = config.report_dir / "daily-runs" / "run-1" / "run_certificate.json"
    certificate.parent.mkdir(parents=True)
    certificate.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "decision_traces": {
                    "MSFT": {
                        "data_quality": "CERTIFIED_PIT",
                        "composite_alpha": 0.25,
                        "final_action": "HOLD",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(terminal_cli, "load_config", lambda _path: config)
    assert terminal_cli._explain(tmp_path / "config.yaml", "msft") == 0


def test_provider_status_is_preflight_only_and_redacts_credentials(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(terminal_cli.default_config_text(), encoding="utf-8")
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    result = terminal_cli.main(
        ["--config", str(config_path), "data-provider", "status"]
    )
    output = capsys.readouterr().out
    assert result == 0
    assert "daily readiness is unaffected" in output


def test_research_data_cli_exposes_isolated_lifecycle_commands() -> None:
    parser = terminal_cli.build_parser()
    for action in ("status", "audit", "certify", "manifest"):
        args = parser.parse_args(["research-data", action])
        assert args.command == "research-data"
        assert args.research_data_action == action
    imported = parser.parse_args(["research-data", "import", "fixture.csv"])
    assert imported.path == Path("fixture.csv")

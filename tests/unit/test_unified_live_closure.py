from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from personal_alpha_terminal.application.app_service import ApplicationService
from personal_alpha_terminal.application.daily_result import (
    DailyQuantResult,
    DecisionReadiness,
    ExecutionPlan,
    PortfolioSummary,
    RiskSummary,
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import resolve_effective_runtime_config
from personal_alpha_terminal.data.database import build_engine, build_session_factory
from personal_alpha_terminal.models import Base, PortfolioTransaction
from personal_alpha_terminal.terminal.cli import build_parser
from personal_alpha_terminal.terminal.daily_renderer import (
    _bar,
    _classified_blockers,
    capture_daily_quant_result,
    display_width,
)


def _result(*, signal_status: StageStatus = StageStatus.FAIL_BLOCKING) -> DailyQuantResult:
    now = datetime(2026, 8, 11, 14, tzinfo=UTC)
    stages = tuple(
        StageResult(
            name,
            signal_status if name == "SIGNAL" else StageStatus.PASS,
            0.0,
            "STRATEGY_NOT_PRODUCTION_APPROVED" if name == "SIGNAL" else "ok",
            {},
        )
        for name in ("CALENDAR", "DATA", "PIT", "FEATURE", "FACTOR", "SIGNAL")
    )
    return DailyQuantResult(
        run_id="run-live-1",
        version="1",
        started_at=now,
        finished_at=now,
        analysis_date=date(2026, 8, 10),
        trade_date=date(2026, 8, 11),
        market_session="REGULAR",
        market_structure="US",
        data_cutoff=now,
        decision_readiness=DecisionReadiness.NOT_ACTIONABLE,
        llm_status="OPTIONAL_OFFLINE",
        stages=stages,
        data_health=(),
        market_regime="REGIME_OPTIONAL_UNAVAILABLE",
        market_regime_detail="optional",
        factors=(),
        probabilities=(),
        candidates=(),
        portfolio=PortfolioSummary("UNCHANGED", 100_000, 100_000, 1.0, 0.0, ()),
        risk=RiskSummary("BLOCKED", None, None, None, None, None, None, None, None, None, ()),
        final_decisions=(),
        rejected_signals=(),
        execution_plan=ExecutionPlan(
            "BLOCKED", True, "Charles Schwab (manual only)", 100_000, 0, 0,
            100_000, None, 0, (),
        ),
        benchmarks=(),
        blockers=("STRATEGY_NOT_PRODUCTION_APPROVED",),
        warnings=("PROBABILITY_NOT_CALIBRATED", "REGIME_OPTIONAL_UNAVAILABLE"),
        provenance={"data_hash": "abc"},
        config_hash="config",
        model_versions=("USAdaptiveAlphaCoreV1:1.0.0",),
    )


def test_product_cli_has_only_one_live_portfolio_mode() -> None:
    parser = build_parser()
    commands = parser._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert "portfolio-init" in commands
    assert "portfolio-update" in commands
    assert not any(name.startswith("paper-") for name in commands)
    parsed = parser.parse_args(["portfolio-init", "--portfolio-id", "main", "--cash", "100000"])
    assert parsed.portfolio_id == "main"
    assert not hasattr(parsed, "mode")


def test_product_source_contains_no_paper_domain() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "personal_alpha_terminal"
    assert not (root / "paper_trading").exists()
    cli = (root / "terminal" / "cli.py").read_text(encoding="utf-8").lower()
    assert "paper_signal" not in cli
    assert "paper_only" not in cli
    assert "simulation only" not in cli


def test_main_initialization_is_exact_and_auditable() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    service = ApplicationService(factory, Settings(database_url="sqlite://"))
    internal_id, warnings = service.create_portfolio_with_positions(
        name="main", cash_balance=Decimal("100000"), as_of_date=date(2026, 8, 11)
    )
    assert warnings == ()
    status = service.get_portfolio_status("main")
    assert status == {
        "id": internal_id,
        "portfolio_id": "main",
        "name": "main",
        "currency": "USD",
        "cash": 100000.0,
        "nav": 100000.0,
        "invested": 0.0,
        "cash_weight": 1.0,
        "as_of": None,
        "positions": (),
    }
    with factory() as session:
        events = tuple(session.scalars(select(PortfolioTransaction)))
    assert len(events) == 1
    assert events[0].transaction_type == "deposit"
    assert events[0].cash_amount == Decimal("100000")
    assert events[0].external_id == "initial-cash:main"

    updated = service.update_portfolio_snapshot(
        portfolio_id="main",
        as_of_date=date(2026, 8, 11),
        positions=(),
        cash_balance=Decimal("90000"),
    )
    assert updated.cash_balance_updated
    assert service.get_portfolio_status("main")["cash"] == 90000.0
    with factory() as session:
        events = tuple(
            session.scalars(select(PortfolioTransaction).order_by(PortfolioTransaction.id))
        )
    assert len(events) == 2
    assert events[1].transaction_type == "withdrawal"
    assert events[1].cash_amount == Decimal("10000")


def test_config_selects_main_by_stable_external_identity(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("market: US\nportfolio_id: main\n", encoding="utf-8")
    assert resolve_effective_runtime_config(path, environment={}).portfolio_id == "main"


def test_signal_gate_remains_closed_but_factor_analysis_is_valid() -> None:
    result = _result()
    assert result.diagnostic_analysis_complete
    assert result.run_classification == "VALID_ANALYSIS_NON_ACTIONABLE"
    assert not result.actionable
    assert result.final_decisions == ()


def test_locales_render_the_same_immutable_result() -> None:
    result = _result()
    before = asdict(result)
    zh = capture_daily_quant_result(result, width=120, locale="zh-CN")
    en = capture_daily_quant_result(result, width=120, locale="en-US")
    assert "【今日操作清单】" in zh
    assert "TODAY ACTION LIST" in en
    assert "STRATEGY_NOT_PRODUCTION_APPROVED" in zh
    assert "STRATEGY_NOT_PRODUCTION_APPROVED" in en
    assert asdict(result) == before


def test_narrow_terminal_falls_back_without_losing_numbers() -> None:
    rendered = capture_daily_quant_result(_result(), width=72, locale="zh-CN")
    assert "$100,000.00" in rendered
    assert "100.00%" in rendered
    assert "Run ID" in rendered


def test_unicode_width_and_charts_match_terminal_cells() -> None:
    assert display_width("组合 A") == 6
    assert display_width("e\N{COMBINING ACUTE ACCENT}") == 1
    chart = _bar(0.63, 10)
    assert chart.count("█") == 6
    assert chart.count("-") == 4
    assert chart.endswith("63.0%")


def test_blocker_priority_does_not_turn_optional_inputs_red() -> None:
    primary, secondary, optional = _classified_blockers(_result())
    assert primary == ["STRATEGY_NOT_PRODUCTION_APPROVED"]
    assert secondary == ["PROBABILITY_NOT_CALIBRATED"]
    assert optional == ["REGIME_OPTIONAL_UNAVAILABLE"]

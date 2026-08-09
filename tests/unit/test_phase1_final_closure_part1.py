from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.daily_orchestrator import DailyQuantOrchestrator
from personal_alpha_terminal.application.daily_result import (
    BenchmarkSummary,
    DailyQuantResult,
    DecisionReadiness,
    ExecutionPlan,
    FactorRow,
    PortfolioSummary,
    RiskSummary,
    StageResult,
    StageStatus,
    build_stage_evidence_chain,
)
from personal_alpha_terminal.application.quant_daily_service import ProductionDailyWorkflow
from personal_alpha_terminal.core.effective_config import resolve_effective_runtime_config
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.validation_artifacts import (
    PortfolioValidationIdentity,
    ProbabilityCalibrationIdentity,
    ValidationArtifactRegistry,
)
from personal_alpha_terminal.terminal import cli


def _config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            (
                "market: US",
                f"cache_dir: {(tmp_path / 'cache').as_posix()}",
                f"report_dir: {(tmp_path / 'reports').as_posix()}",
                "timeout_seconds: 11",
                "provider_priority:",
                "  - yahoo",
                "  - stooq",
            )
        ),
        encoding="utf-8",
    )
    return path


def test_effective_config_is_single_resolved_source_and_hashes_are_stable(
    tmp_path: Path,
) -> None:
    path = _config_file(tmp_path)
    one = resolve_effective_runtime_config(
        path, environment={"PAT_MARKET_DATA_TIMEOUT_SECONDS": "17"}
    )
    two = resolve_effective_runtime_config(
        path, environment={"PAT_MARKET_DATA_TIMEOUT_SECONDS": "17"}
    )
    assert one.timeout_seconds == 17
    assert one.settings.market_data_timeout_seconds == 17
    assert one.runtime_config_hash == two.runtime_config_hash
    assert one.canonical_run_config_hash == two.canonical_run_config_hash
    assert one.settings.market_data_provider_cache_dir == one.cache_dir


def test_yaml_holdings_cannot_become_real_portfolio(tmp_path: Path) -> None:
    path = _config_file(tmp_path)
    path.write_text(path.read_text(encoding="utf-8") + "\nholdings:\n  AAPL: 1\n")
    with pytest.raises(ValueError, match="portfolio ledger"):
        resolve_effective_runtime_config(path)


def _portfolio_identity(config, *, risk_hash: str | None = None) -> PortfolioValidationIdentity:
    return PortfolioValidationIdentity(
        alpha_model_version="USAdaptiveAlphaCoreV1:1.0.0",
        alpha_data_version="data-v1",
        strategy_parameter_hash=config.strategy_parameter_hash,
        portfolio_constraint_hash=config.portfolio_constraint_hash,
        risk_model_hash=risk_hash or config.risk_model_hash,
        cost_model_hash=config.cost_model_hash,
        runtime_config_hash=config.runtime_config_hash,
        benchmark_definition="SPY",
    )


def test_portfolio_approval_requires_exact_produced_artifact(tmp_path: Path) -> None:
    config = resolve_effective_runtime_config(_config_file(tmp_path))
    registry = ValidationArtifactRegistry(config.validation_artifact_dir)
    identity = _portfolio_identity(config)
    assert registry.matching_portfolio_approval(identity) is None
    artifact = registry.produce_portfolio_approval(
        validation_id="approval-001",
        locked_oos_evidence_id="locked-oos-001",
        identity=identity,
        validation_start=date(2018, 1, 1),
        validation_end=date(2024, 12, 31),
        embargo_sessions=21,
        walk_forward_configuration="expanding-3y-1y",
        source_git_commit="a" * 40,
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    assert registry.matching_portfolio_approval(identity) == artifact
    assert registry.matching_portfolio_approval(
        replace(identity, risk_model_hash="different")
    ) is None
    workflow = ProductionDailyWorkflow(Session(), config)
    assert workflow._pipeline(None).construction.constraints.model_validation_id is None
    assert (
        workflow._pipeline(artifact.validation_id).construction.constraints.model_validation_id
        == artifact.validation_id
    )


def test_model_approval_does_not_imply_probability_calibration(tmp_path: Path) -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    signal = AlphaSignal(
        symbol="MSFT",
        as_of=now,
        signal_type="factor",
        expected_excess_return=0.01,
        horizon=21,
        raw_signal=1.0,
        normalized_signal=0.5,
        confidence=0.0,
        confidence_calibrated=False,
        sample_size=100,
        statistical_strength=0.5,
        economic_strength=0.5,
        decay_half_life=21,
        valid_until=now + timedelta(days=30),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=AlphaValidationStatus.PRODUCTION_APPROVED,
        model_version="USAdaptiveAlphaCoreV1:1.0.0:x",
        data_version="data-v1",
        evidence_coverage=0.9,
    )
    assert signal.evidence_coverage == 0.9
    assert not signal.production_eligible(now)
    registry = ValidationArtifactRegistry(tmp_path / "artifacts")
    identity = ProbabilityCalibrationIdentity(
        "USAdaptiveAlphaCoreV1:1.0.0", "data-v1", "strategy-hash"
    )
    assert registry.matching_probability_calibration(identity) is None
    artifact = registry.produce_probability_calibration(
        calibration_id="cal-001",
        identity=identity,
        method="isotonic",
        calibration_version="1",
        train_start=date(2015, 1, 1),
        train_end=date(2019, 12, 31),
        calibration_start=date(2020, 1, 1),
        calibration_end=date(2021, 12, 31),
        oos_start=date(2022, 1, 1),
        oos_end=date(2024, 12, 31),
        brier_score=0.22,
        log_loss=0.64,
        expected_calibration_error=0.03,
        sample_count=500,
        reliability_bins=((0.2, 0.21, 100),),
        created_at=now,
    )
    assert registry.matching_probability_calibration(identity) == artifact


def _result() -> DailyQuantResult:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    return DailyQuantResult(
        run_id="run-1",
        version="1.1.0",
        started_at=now,
        finished_at=now + timedelta(seconds=1),
        analysis_date=date(2026, 8, 7),
        trade_date=date(2026, 8, 10),
        market_session="CLOSED",
        market_structure="LEGACY_US_EQUITY",
        data_cutoff=now,
        decision_readiness=DecisionReadiness.NOT_ACTIONABLE,
        llm_status="OPTIONAL/OFFLINE",
        stages=(
            StageResult("CALENDAR", StageStatus.PASS, 0.1, "ok", {"output_row_count": 1}),
            StageResult("DATA", StageStatus.FAIL_BLOCKING, 0.2, "blocked", {}),
        ),
        data_health=(),
        market_regime="UNAVAILABLE",
        market_regime_detail="not run",
        factors=(),
        probabilities=(),
        candidates=(),
        portfolio=PortfolioSummary("NOT_INITIALIZED", None, None, None, None, ()),
        risk=RiskSummary("BLOCKED", None, None, None, None, None, None, None, None, None, ()),
        final_decisions=(),
        rejected_signals=(),
        execution_plan=ExecutionPlan("BLOCKED", True, "manual", None, 0, 0, None, None, 0, ()),
        benchmarks=(BenchmarkSummary("SPY", "UNAVAILABLE", 0, None, None, "blocked"),),
        blockers=("blocked",),
        warnings=(),
        provenance={
            "build_identifier": "source",
            "identity_hashes": {
                "runtime_config_hash": "runtime",
                "data_version_hash": "data",
            },
        },
        config_hash="root",
        model_versions=(),
    )


def test_stage_evidence_is_sequential_and_tamper_evident() -> None:
    result = _result()
    chain = build_stage_evidence_chain(result)
    assert chain[1]["previous_stage_output_hash"] == chain[0]["output_hash"]
    changed = replace(
        result,
        stages=(result.stages[0], replace(result.stages[1], message="different")),
    )
    assert build_stage_evidence_chain(changed)[-1]["output_hash"] != chain[-1]["output_hash"]


def test_trace_marks_uncaptured_intermediates_instead_of_copying_values() -> None:
    factor = FactorRow("MSFT", {"momentum": 1.0}, 1.0, 1, 0.01, 0.8, "DIAGNOSTIC")
    trace = DailyQuantOrchestrator._decision_traces(
        (factor,), (), {"MSFT": 0.1}, {"MSFT": 0.05}
    )["MSFT"]
    assert trace["factor_raw_values"] == "NOT_CAPTURED"
    assert trace["factor_normalized_values"] == "NOT_CAPTURED"
    assert trace["factor_neutralized_values"] == {"momentum": 1.0}
    assert trace["portfolio_optimized_target"] == "NOT_CAPTURED"
    assert trace["data_quality"] == "NOT_CAPTURED"


def test_section_cli_reads_immutable_run_without_running_daily(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _config_file(tmp_path)
    config = resolve_effective_runtime_config(config_path)
    certificate = config.report_dir / "daily-runs" / "run-1" / "run_certificate.json"
    certificate.parent.mkdir(parents=True)
    certificate.write_text(
        json.dumps({"run_id": "run-1", "factor_statistics": {}, "signals": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "run_daily",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert cli.main(["--config", str(config_path), "factors", "--run-id", "run-1"]) == 0

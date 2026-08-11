from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.daily_result import (
    BenchmarkSummary,
    DailyQuantResult,
    DataHealthItem,
    DecisionReadiness,
    DecisionRow,
    ExecutionLeg,
    ExecutionPlan,
    FactorRow,
    PortfolioPositionRow,
    PortfolioSummary,
    ProbabilityRow,
    RiskSummary,
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.market_data_certification import (
    CertificationStatus,
    InstrumentEvidence,
    RealMarketDataCertificationValidator,
    SourceBar,
)
from personal_alpha_terminal.data.market_data_quality.schemas import MarketSegment
from personal_alpha_terminal.data.us_market.pit_total_return import (
    PITRawBar,
    PointInTimeTotalReturnBuilder,
)
from personal_alpha_terminal.models import Base
from personal_alpha_terminal.quant_engine.model_registry import (
    ModelPromotionEvidence,
    ModelRegistryService,
)
from personal_alpha_terminal.quant_engine.pit import PITStatus, select_universe_snapshot
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantOutput,
    DailyQuantPipeline,
    ProductionPipelineStatus,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    CorrelationRiskStatus,
    PortfolioRiskState,
)
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    StrategyAlphaResult,
    USAdaptiveAlphaCoreV1,
)
from personal_alpha_terminal.quant_engine.validation_artifacts import (
    PortfolioValidationIdentity,
    ProbabilityCalibrationIdentity,
    ValidationArtifactRegistry,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)
from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result

pytestmark = pytest.mark.quant_critical

DECISION_TIME = datetime(2027, 8, 8, 18, tzinfo=UTC)
LAST_SESSION = date(2027, 8, 6)
SYMBOLS = ("AAA", "BBB", "CCC", "DDD", "EEE")


def _source_bar(symbol: str, source: str, day: date, close: float) -> SourceBar:
    value = Decimal(str(close))
    return SourceBar(
        source=f"{source}:{symbol}",
        provider=f"{source}.daily",
        trade_date=day,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1000000"),
        adjusted_close=value,
    )


def _instrument_result(symbol: str, *, disagree: bool = False):
    sessions = (date(2027, 8, 5), LAST_SESSION)
    primary = (100.0, 101.0)
    secondary = (100.0, 120.0) if disagree else (100.0, 101.0)
    bars = tuple(
        _source_bar(symbol, source, session, values[index])
        for source, values in (("primary", primary), ("secondary", secondary))
        for index, session in enumerate(sessions)
    )
    return RealMarketDataCertificationValidator().validate_instrument(
        InstrumentEvidence(
            symbol=symbol,
            market="US",
            segment=MarketSegment.NASDAQ,
            security_type="stock",
            expected_sessions=sessions,
            bars=bars,
            action_coverage_sources=("primary-actions", "secondary-actions"),
        )
    )


def _producer_evidence():
    certifications = tuple(_instrument_result(symbol) for symbol in SYMBOLS)
    assert all(item.status is CertificationStatus.PASSED for item in certifications)
    universe = select_universe_snapshot(
        pd.DataFrame(
            {
                "snapshot_id": ["vertical-universe-v1"] * len(SYMBOLS),
                "snapshot_date": [LAST_SESSION] * len(SYMBOLS),
                "available_at": [DECISION_TIME - timedelta(days=1)] * len(SYMBOLS),
                "permanent_security_id": SYMBOLS,
                "listing_date": [date(2020, 1, 2)] * len(SYMBOLS),
                "delisting_date": [None] * len(SYMBOLS),
                "source": ["fixture-membership-archive"] * len(SYMBOLS),
            }
        ),
        information_cutoff=DECISION_TIME,
        certified_history=True,
    )
    assert universe.status is PITStatus.VALID
    pit_series = tuple(
        PointInTimeTotalReturnBuilder().build(
            bars=(
                PITRawBar(
                    symbol,
                    date(2027, 8, 5),
                    100.0,
                    f"primary:{symbol}",
                    DECISION_TIME - timedelta(days=2),
                ),
                PITRawBar(
                    symbol,
                    LAST_SESSION,
                    101.0,
                    f"primary:{symbol}",
                    DECISION_TIME - timedelta(days=1),
                ),
            ),
            actions=(),
            as_of_time=DECISION_TIME,
        )
        for symbol in SYMBOLS
    )
    data_version = fingerprint(
        {
            "instrument_certification": [asdict(item) for item in certifications],
            "pit_total_return_versions": [item.version_id for item in pit_series],
            "universe": universe.frame.to_dict("records"),
        }
    )
    evidence = ResearchDataEvidence(
        market="US",
        asset_type="stock",
        quality_status="passed",
        source="canonical producer fixture",
        provider="primary+secondary",
        source_ids=tuple(
            sorted(
                source_id
                for item in pit_series
                for source_id in item.source_ids
            )
        ),
        latest_available_time=DECISION_TIME - timedelta(days=1),
        point_in_time_status="certified",
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="vertical-universe-v1",
        universe_available_time=DECISION_TIME - timedelta(days=1),
        corporate_actions_complete=all(
            item.status is CertificationStatus.PASSED for item in certifications
        ),
        trading_calendar_complete=True,
        missing_rate=0.0,
        anomaly_rate=0.0,
        maximum_missing_rate=0.01,
        maximum_anomaly_rate=0.01,
        data_version=data_version,
        allow_backtest=True,
        allow_display=True,
        allow_portfolio_decision=True,
        dual_source_verified=all(item.source_count >= 2 for item in certifications),
    )
    request = ResearchDataRequest(
        purpose=ResearchPurpose.PORTFOLIO_DECISION,
        market="US",
        asset_type="stock",
        start_date=date(2027, 8, 5),
        end_date=LAST_SESSION,
        decision_time=DECISION_TIME,
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="vertical-universe-v1",
    )
    authorization = ResearchDataGate().authorize(
        request, evidence, evaluated_at=DECISION_TIME
    )
    return authorization, data_version


def _price_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    sessions = pd.date_range(end=LAST_SESSION, periods=320, freq="B")
    rows: list[dict[str, object]] = []
    wide: dict[str, pd.Series] = {}
    for index, symbol in enumerate(SYMBOLS):
        x = np.arange(len(sessions), dtype=float)
        close = 80 + index * 7 + x * (0.03 + index * 0.002) + np.sin(x / (9 + index))
        series = pd.Series(close, index=sessions, name=symbol)
        wide[symbol] = series.pct_change().fillna(0)
        rows.extend(
            {
                "permanent_security_id": symbol,
                "ticker": symbol,
                "trade_date": session.date(),
                "available_time": datetime.combine(
                    session.date(), datetime.min.time(), tzinfo=UTC
                )
                + timedelta(hours=22),
                "close": float(value),
            }
            for session, value in zip(sessions, close, strict=True)
        )
    metadata = pd.DataFrame(
        {
            "permanent_security_id": SYMBOLS,
            "sector": ["Technology", "Technology", "Technology", "Healthcare", "Healthcare"],
            "market_cap": [10e9, 20e9, 30e9, 40e9, 50e9],
        }
    )
    returns = pd.DataFrame(wide)
    returns.index = returns.index.tz_localize("UTC")
    benchmark = returns.mean(axis=1).rename("SPY")
    return pd.DataFrame(rows), metadata, returns, benchmark


def _produce_models(tmp_path: Path, data_version: str):
    config = EffectiveRuntimeConfig(report_dir=tmp_path / "reports")
    registry = ValidationArtifactRegistry(config.validation_artifact_dir)
    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    identity = PortfolioValidationIdentity(
        alpha_model_version=f"{strategy.model_id}:{strategy.version}",
        alpha_data_version=data_version,
        strategy_parameter_hash=strategy.config.parameter_fingerprint,
        portfolio_constraint_hash=config.portfolio_constraint_hash,
        risk_model_hash=config.risk_model_hash,
        cost_model_hash=config.cost_model_hash,
        runtime_config_hash=config.runtime_config_hash,
        benchmark_definition=config.benchmark,
    )
    portfolio_artifact = registry.produce_portfolio_approval(
        validation_id="vertical-portfolio-validation",
        locked_oos_evidence_id="vertical-locked-oos-evidence",
        identity=identity,
        validation_start=date(2024, 1, 2),
        validation_end=date(2026, 12, 31),
        embargo_sessions=21,
        walk_forward_configuration="expanding-252-63",
        source_git_commit="synthetic-code-path-only",
        created_at=DECISION_TIME - timedelta(days=2),
    )
    probability_artifact = registry.produce_probability_calibration(
        calibration_id="vertical-probability-calibration",
        identity=ProbabilityCalibrationIdentity(
            alpha_model_version=f"{strategy.model_id}:{strategy.version}",
            alpha_data_version=data_version,
            strategy_parameter_hash=strategy.config.parameter_fingerprint,
        ),
        method="isotonic",
        calibration_version="vertical-v1",
        train_start=date(2021, 1, 1),
        train_end=date(2022, 12, 31),
        calibration_start=date(2023, 1, 1),
        calibration_end=date(2023, 12, 31),
        oos_start=date(2024, 1, 1),
        oos_end=date(2026, 12, 31),
        brier_score=0.20,
        log_loss=0.60,
        expected_calibration_error=0.03,
        sample_count=500,
        reliability_bins=((0.4, 0.41, 100), (0.6, 0.59, 100)),
        created_at=DECISION_TIME - timedelta(days=2),
    )
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    models = ModelRegistryService(session)
    record = models.ensure_registered(
        model_id=strategy.model_id,
        version=strategy.version,
        objective="vertical production contract",
        inputs=["PIT prices"],
        data_requirements=["dual source", "PIT universe"],
        hyperparameters=asdict(config.strategy),
        limitations=["synthetic fixture proves code path only"],
    )
    record.status = "Tested"
    models.promote(
        record,
        ModelPromotionEvidence(
            data_version=data_version,
            parameter_fingerprint=config.strategy_parameter_hash,
            validation_manifest_hash=portfolio_artifact.artifact_hash,
            locked_oos=probability_artifact.locked_oos,
            pit_certified=True,
            survivorship_bias_controlled=True,
            costs_included=True,
            approved_by="deterministic vertical test producer",
            notes="fixture-only; never upgrades live-capital readiness",
        ),
    )
    approval = models.production_approval(
        model_id=strategy.model_id,
        version=strategy.version,
        data_version=data_version,
        parameter_fingerprint=config.strategy_parameter_hash,
        decision_time=DECISION_TIME,
    )
    assert approval is not None
    return (
        config,
        registry,
        portfolio_artifact,
        probability_artifact,
        strategy,
        approval,
        engine,
        session,
    )


def _run_vertical(tmp_path: Path, *, calibrated: bool = True):
    authorization, data_version = _producer_evidence()
    prices, metadata, returns, benchmark = _price_inputs()
    config, registry, portfolio_artifact, calibration, strategy, approval, engine, session = (
        _produce_models(tmp_path, data_version)
    )
    alpha = strategy.generate(
        prices=prices,
        metadata=metadata,
        decision_time=DECISION_TIME,
        data_version=data_version,
        approval=approval,
        calibration=calibration if calibrated else None,
    )
    market_caps = metadata.set_index("permanent_security_id")["market_cap"]
    log_caps = np.log(market_caps.astype(float))
    size_scores = (log_caps - log_caps.mean()) / log_caps.std(ddof=1)
    risk_metadata = tuple(
        AssetRiskMetadata(
            symbol,
            str(metadata.loc[metadata["permanent_security_id"] == symbol, "sector"].iloc[0]),
            50_000_000,
            float(size_scores[symbol]),
        )
        for symbol in SYMBOLS
    )
    constraints = replace(
        config.portfolio_constraints,
        model_validation_id=portfolio_artifact.validation_id,
    )
    pipeline = DailyQuantPipeline(
        construction=PortfolioConstructionEngine(constraints),
        stress_config=StressRiskConfig(
            **{
                **asdict(config.stress_risk),
                "production_validated": True,
                "validation_id": portfolio_artifact.validation_id,
            }
        ),
    )
    inputs = DailyQuantInput(
        authorization=authorization,
        decision_time=DECISION_TIME,
        alpha_signals=alpha.signals,
        returns=returns,
        benchmark_returns=benchmark,
        risk_metadata=risk_metadata,
        current_weights={},
        portfolio_value=1_000_000,
        portfolio_risk_state=PortfolioRiskState(
            0.0,
            0.0,
            0.0,
            0.0,
            None,
            None,
            CorrelationRiskStatus.NOT_APPLICABLE,
        ),
        regime=None,
        pit_valid=True,
        universe_snapshot_id="vertical-universe-v1",
        data_quality="CERTIFIED",
    )
    return (
        pipeline.run(inputs),
        alpha,
        config,
        registry,
        portfolio_artifact,
        calibration,
        data_version,
        engine,
        session,
    )


def _terminal_result(
    output: DailyQuantOutput,
    alpha: StrategyAlphaResult,
    config: EffectiveRuntimeConfig,
    data_version: str,
) -> DailyQuantResult:
    assert output.target is not None and output.risk is not None and output.stress is not None
    stages = tuple(
        StageResult(
            name,
            StageStatus.PASS,
            0.0,
            "vertical producer output",
            {"output_row_count": 1},
        )
        for name in (
            "CALENDAR", "DATA", "PIT", "FEATURE", "FACTOR", "SIGNAL",
            "PROBABILITY", "PORTFOLIO", "RISK", "DECISION", "EXECUTION", "PERSISTENCE",
        )
    )
    factors = tuple(
        FactorRow(
            item.symbol,
            item.components,
            item.composite,
            item.rank,
            item.expected_alpha,
            item.evidence_coverage,
            item.status,
            item.raw_values,
            item.winsorized_values,
            item.neutralized_values,
            item.neutralization_evidence,
        )
        for item in alpha.factors
    )
    decisions = tuple(
        DecisionRow(
            f"vertical:{item.ticker}",
            item.ticker,
            item.action.value,
            item.current_weight,
            item.target_weight,
            item.delta_weight,
            item.estimated_trade_value,
            max(1, int(item.estimated_trade_value / 100)),
            item.estimated_cost,
            item.expected_alpha,
            item.confidence,
            item.risk_contribution,
            item.reason,
            item.data_quality,
            item.model_version,
            item.data_version,
            DECISION_TIME + timedelta(days=1),
            DECISION_TIME + timedelta(days=6),
        )
        for item in output.trades
    )
    legs = tuple(
        ExecutionLeg(
            index,
            item.symbol,
            item.action,
            item.estimated_value,
            item.estimated_quantity,
            item.estimated_cost,
            item.earliest_execution_time,
        )
        for index, item in enumerate(decisions, 1)
        if item.action != "HOLD"
    )
    positions = tuple(
        PortfolioPositionRow(symbol, None, None, 0.0, weight, weight)
        for symbol, weight in output.target.target_weights.items()
    )
    return DailyQuantResult(
        run_id="vertical-production-contract",
        version="1.1.0",
        started_at=DECISION_TIME,
        finished_at=DECISION_TIME + timedelta(seconds=1),
        analysis_date=LAST_SESSION,
        trade_date=date(2027, 8, 9),
        market_session="CLOSED",
        market_structure="LEGACY_US_EQUITY",
        data_cutoff=DECISION_TIME,
        decision_readiness=DecisionReadiness.READY,
        llm_status="OPTIONAL/OFFLINE",
        stages=stages,
        data_health=(
            DataHealthItem(
                "POINT_IN_TIME_TOTAL_RETURN", LAST_SESSION, LAST_SESSION, 0, 1.0, 0.0,
                "primary+secondary", StageStatus.PASS, "producer certified",
            ),
        ),
        market_regime="NOT_CALIBRATED",
        market_regime_detail="no regime probability affected the target",
        factors=factors,
        probabilities=(
            ProbabilityRow(
                "locked OOS calibration artifact", "alpha confidence", 500, None,
                None, None, None, None, None, None, None, "CALIBRATED",
                "LOCKED_OOS", "PASS",
            ),
        ),
        candidates=factors,
        portfolio=PortfolioSummary(
            "TARGET_COMPUTED", 1_000_000, None, output.target.cash_weight,
            sum(output.target.target_weights.values()), positions,
        ),
        risk=RiskSummary(
            "PASS", None, config.portfolio_constraints.target_annualized_volatility,
            0.0, sum(value**2 for value in output.target.target_weights.values()),
            output.target.turnover, sum(output.target.target_weights.values()),
            output.target.cash_weight, 1.0,
            max(output.target.target_weights.values(), default=0.0),
            output.target.risk_reductions,
            size_exposure_status=output.risk.size_exposure_status.value,
            stress_status=output.stress.status.value,
            stress_failures=output.stress.hard_failures,
            stress_warnings=output.stress.warnings,
        ),
        final_decisions=decisions,
        rejected_signals=(),
        execution_plan=ExecutionPlan(
            "MANUAL_ONLY", True, "Charles Schwab", 1_000_000,
            0.0, sum(item.estimated_value for item in legs),
            1_000_000 - sum(item.estimated_value + item.estimated_cost for item in legs),
            output.target.turnover, sum(item.estimated_cost for item in legs), legs,
        ),
        benchmarks=(BenchmarkSummary("SPY", "PIT PROXY", 319, None, None, "same cutoff"),),
        blockers=(),
        warnings=("fixture proves code path, not live readiness",),
        provenance={
            "git_commit": "synthetic-code-path-only",
            "randomness": "NOT_USED",
            "identity_hashes": {
                "runtime_config_hash": config.runtime_config_hash,
                "strategy_parameter_hash": config.strategy_parameter_hash,
                "data_version_hash": data_version,
                "portfolio_constraint_hash": config.portfolio_constraint_hash,
                "risk_model_hash": config.risk_model_hash,
                "cost_model_hash": config.cost_model_hash,
            },
        },
        config_hash=config.canonical_run_config_hash,
        model_versions=tuple(sorted({item.model_version for item in alpha.signals})),
    )


def test_fully_validated_synthetic_vertical_path_persists_and_renders_identity(
    tmp_path: Path,
) -> None:
    output, alpha, config, _registry, _artifact, _calibration, data_version, engine, session = (
        _run_vertical(tmp_path)
    )
    try:
        assert output.status is ProductionPipelineStatus.READY, output.blockers
        assert output.decision is not None
        result = _terminal_result(output, alpha, config, data_version)
        snapshot = result.persist(tmp_path / "snapshots")
        certificate = result.persist_evidence(tmp_path / "evidence")
        persisted = json.loads(snapshot.read_text(encoding="utf-8"))
        rendered = capture_daily_quant_result(result, width=120)

        assert persisted["final_decisions"] == [
            asdict(item) | {
                "earliest_execution_time": item.earliest_execution_time.isoformat(),
                "expiry": item.expiry.isoformat(),
            }
            for item in result.final_decisions
        ]
        assert tuple(item.ticker for item in output.decision.proposals) == tuple(
            item.symbol for item in result.final_decisions
        )
        assert all(item.symbol in rendered for item in result.final_decisions)
        assert certificate.exists()
        assert result.actionable
    finally:
        session.close()
        engine.dispose()


def test_provider_disagreement_producer_blocks_authorization() -> None:
    failed = _instrument_result("AAA", disagree=True)
    assert failed.status is CertificationStatus.FAILED
    assert failed.price_mismatches > 0


def test_pit_builder_rejects_future_bar_before_portfolio() -> None:
    with pytest.raises(ValueError, match="unavailable at the requested PIT cutoff"):
        PointInTimeTotalReturnBuilder().build(
            bars=(
                PITRawBar(
                    "AAA",
                    date(2027, 8, 5),
                    100,
                    "source",
                    DECISION_TIME - timedelta(days=1),
                ),
                PITRawBar("AAA", LAST_SESSION, 101, "source", DECISION_TIME + timedelta(seconds=1)),
            ),
            actions=(),
            as_of_time=DECISION_TIME,
        )


def test_missing_or_mismatched_portfolio_approval_blocks(tmp_path: Path) -> None:
    output, alpha, config, registry, artifact, _calibration, data_version, engine, session = (
        _run_vertical(tmp_path)
    )
    try:
        authorization, _ = _producer_evidence()
        _prices, _metadata, returns, benchmark = _price_inputs()
        risk_metadata = tuple(
            AssetRiskMetadata(symbol, "Technology", 50_000_000, float(index - 2))
            for index, symbol in enumerate(SYMBOLS)
        )
        missing = DailyQuantPipeline(
            construction=PortfolioConstructionEngine(config.portfolio_constraints)
        ).run(
            DailyQuantInput(
                authorization, DECISION_TIME, alpha.signals, returns, benchmark,
                risk_metadata, {}, 1_000_000,
                PortfolioRiskState(0, 0, 0, 0, None, None, CorrelationRiskStatus.NOT_APPLICABLE),
                None, True, "vertical-universe-v1", "CERTIFIED",
            )
        )
        mismatch = registry.matching_portfolio_approval(
            replace(artifact.identity, risk_model_hash="changed-risk-hash")
        )
        assert output.status is ProductionPipelineStatus.READY
        assert missing.status is ProductionPipelineStatus.BLOCKED
        assert "locked OOS validation manifest" in missing.blockers[0]
        assert mismatch is None
        assert data_version == artifact.identity.alpha_data_version
    finally:
        session.close()
        engine.dispose()


def test_stress_veto_empties_execution_plan(tmp_path: Path) -> None:
    output, alpha, config, _registry, artifact, _calibration, _data, engine, session = (
        _run_vertical(tmp_path)
    )
    try:
        authorization, _ = _producer_evidence()
        _prices, metadata, returns, benchmark = _price_inputs()
        risk_metadata = tuple(
            AssetRiskMetadata(
                symbol,
                str(metadata.loc[metadata["permanent_security_id"] == symbol, "sector"].iloc[0]),
                50_000_000,
                float(index - 2),
            )
            for index, symbol in enumerate(SYMBOLS)
        )
        veto = DailyQuantPipeline(
            construction=PortfolioConstructionEngine(
                replace(config.portfolio_constraints, model_validation_id=artifact.validation_id)
            ),
            stress_config=StressRiskConfig(
                production_validated=True,
                validation_id=artifact.validation_id,
                maximum_single_name_loss=0.001,
            ),
        ).run(
            DailyQuantInput(
                authorization, DECISION_TIME, alpha.signals, returns, benchmark,
                risk_metadata, {}, 1_000_000,
                PortfolioRiskState(0, 0, 0, 0, None, None, CorrelationRiskStatus.NOT_APPLICABLE),
                None, True, "vertical-universe-v1", "CERTIFIED",
            )
        )
        assert output.status is ProductionPipelineStatus.READY
        assert veto.status is ProductionPipelineStatus.BLOCKED
        assert veto.trades == ()
        assert veto.decision is None
        assert any("stress veto" in item for item in veto.blockers)
    finally:
        session.close()
        engine.dispose()


def test_probability_without_calibration_never_becomes_probability(tmp_path: Path) -> None:
    output, alpha, _config, _registry, _artifact, _calibration, _data, engine, session = (
        _run_vertical(tmp_path, calibrated=False)
    )
    try:
        assert alpha.factors
        assert all(item.evidence_coverage > 0 for item in alpha.signals)
        assert all(not item.confidence_calibrated for item in alpha.signals)
        assert all(item.confidence == 0 for item in alpha.signals)
        assert output.status is ProductionPipelineStatus.READY
        assert output.target is not None
        assert output.blockers == ()
    finally:
        session.close()
        engine.dispose()

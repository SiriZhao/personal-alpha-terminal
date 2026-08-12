from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from personal_alpha_terminal.application.operational_readiness import (
    OperationalApprovalIdentity,
    ProvisionalOperationalRegistry,
)
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.factors.cross_sectional import (
    FactorSignalStatus,
    FactorSpec,
    process_cross_section,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
    ProductionPipelineStatus,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    CorrelationRiskStatus,
    PortfolioRiskState,
    RiskBudget,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    AssetRiskMetadata,
    PortfolioRiskModel,
    RiskModelConfig,
)
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

NOW = datetime(2026, 8, 8, 21, tzinfo=UTC)
SYMBOLS = ("A", "B", "C", "D")


def _identity(*, factor_config_hash: str = "factor-v1") -> OperationalApprovalIdentity:
    return OperationalApprovalIdentity(
        strategy_name="USAdaptiveAlphaCoreV1",
        strategy_version="1.0.0",
        factor_config_hash=factor_config_hash,
        operational_universe_policy="universe-v1",
        required_factor_lookbacks=(
            ("momentum", 252),
            ("trend", 126),
            ("volatility", 63),
        ),
        portfolio_config_hash="portfolio-v1",
        risk_config_hash="risk-v1",
        cost_model_hash="cost-v1",
    )


def _authorization() -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 8, 7),
        NOW,
        "point_in_time_total_return",
        "universe-v1",
        timedelta(days=5),
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "primary",
        "fixture-adapter",
        ("source-a", "source-b"),
        NOW - timedelta(days=1),
        "certified",
        "point_in_time_total_return",
        "universe-v1",
        NOW - timedelta(days=2),
        True,
        True,
        0.0,
        0.0,
        0.0,
        0.0,
        "data-v1",
        True,
        True,
        True,
        True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=NOW)


def _market_data(seed: int = 7) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0003, 0.009, 180)
    values = {
        symbol: 0.8 * market + rng.normal(0.0002 + index * 0.00005, 0.006, 180)
        for index, symbol in enumerate(SYMBOLS)
    }
    index = pd.bdate_range("2025-11-24", periods=180)
    return pd.DataFrame(values, index=index), pd.Series(market, index=index)


def _metadata() -> tuple[AssetRiskMetadata, ...]:
    return tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 2 else "Healthcare",
            50_000_000 + index * 10_000_000,
            (index - 1.5) / 4,
        )
        for index, symbol in enumerate(SYMBOLS)
    )


def _alpha(
    symbol: str,
    status: AlphaValidationStatus = AlphaValidationStatus.PROVISIONAL_OPERATIONAL_APPROVED,
) -> AlphaSignal:
    return AlphaSignal(
        symbol=symbol,
        as_of=NOW - timedelta(hours=1),
        signal_type="momentum",
        expected_excess_return=0.012,
        horizon=20,
        raw_signal=1.0,
        normalized_signal=0.8,
        confidence=0.8,
        confidence_calibrated=False,
        sample_size=200,
        statistical_strength=0.75,
        economic_strength=0.70,
        decay_half_life=40,
        valid_until=NOW + timedelta(days=3),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=status,
        model_version="USAdaptiveAlphaCoreV1:1.0.0:factor-v1",
        data_version="data-v1",
        operational_approval_hash=(
            "provisional-operational-test"
            if status is AlphaValidationStatus.PROVISIONAL_OPERATIONAL_APPROVED
            else None
        ),
    )


def _constraints(*, model_validation_id: str) -> PortfolioConstraints:
    return PortfolioConstraints(
        maximum_position_weight=0.30,
        maximum_sector_weight=0.50,
        maximum_cluster_weight=0.60,
        maximum_hhi=0.30,
        minimum_cash_weight=0.15,
        maximum_gross_exposure=0.85,
        target_annualized_volatility=0.25,
        maximum_beta=1.10,
        maximum_turnover=0.80,
        maximum_size_exposure=0.50,
        no_trade_band=0.002,
        minimum_rebalance_weight=0.003,
        minimum_trade_value=50,
        risk_aversion=2.0,
        turnover_penalty=0.001,
        model_validation_id=model_validation_id,
    )


def _pipeline(*, operational_mode: bool) -> DailyQuantPipeline:
    validation_id = "provisional-oos-v1"
    return DailyQuantPipeline(
        construction=PortfolioConstructionEngine(
            _constraints(model_validation_id=validation_id),
            operational_mode=operational_mode,
        ),
        stress_config=StressRiskConfig(
            production_validated=not operational_mode,
            validation_id=validation_id,
            provisional_operational=operational_mode,
            maximum_single_name_loss=0.10,
            maximum_sector_loss=0.20,
        ),
        operational_mode=operational_mode,
    )


def test_provisional_approval_is_immutable_and_invalidates_on_config_change(
    tmp_path: Path,
) -> None:
    registry = ProvisionalOperationalRegistry(tmp_path / "approvals")
    artifact = registry.produce(
        identity=_identity(),
        created_at=NOW,
        approval_reason="isolated provisional operational test",
        research_certification_state="NOT_CERTIFIABLE",
    )
    assert registry.matching_approval(_identity()) is not None
    assert registry.matching_approval(_identity()).approval_id == artifact.approval_id
    changed = replace(_identity(), factor_config_hash="factor-v2")
    assert registry.matching_approval(changed) is None


def test_provisional_alpha_is_operational_but_not_production_eligible() -> None:
    signal = _alpha("A")
    assert signal.operational_eligible(NOW)
    assert signal.production_eligible(NOW) is False


def test_provisional_pipeline_is_actionable_but_not_production_approved() -> None:
    returns, benchmark = _market_data()
    pipeline = _pipeline(operational_mode=True)
    output = pipeline.run(
        DailyQuantInput(
            authorization=_authorization(),
            decision_time=NOW,
            alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
            returns=returns,
            benchmark_returns=benchmark,
            risk_metadata=_metadata(),
            current_weights={},
            portfolio_value=1_000_000,
            portfolio_risk_state=PortfolioRiskState(
                -0.01,
                0.12,
                0.0,
                0.0,
                0.3,
                0.25,
                CorrelationRiskStatus.NOT_APPLICABLE,
            ),
            regime=None,
            pit_valid=True,
            universe_snapshot_id="universe-v1",
            data_quality="CERTIFIED",
        )
    )
    assert output.status is ProductionPipelineStatus.READY
    assert output.target is not None
    assert output.target.operational_approved
    assert output.target.production_approved is False
    assert output.trades
    assert output.decision is not None


def test_full_production_path_remains_production_approved() -> None:
    returns, benchmark = _market_data()
    pipeline = _pipeline(operational_mode=False)
    output = pipeline.run(
        DailyQuantInput(
            authorization=_authorization(),
            decision_time=NOW,
            alpha_signals=tuple(
                _alpha(symbol, AlphaValidationStatus.PRODUCTION_APPROVED)
                for symbol in SYMBOLS
            ),
            returns=returns,
            benchmark_returns=benchmark,
            risk_metadata=_metadata(),
            current_weights={},
            portfolio_value=1_000_000,
            portfolio_risk_state=PortfolioRiskState(
                -0.01,
                0.12,
                0.0,
                0.0,
                0.3,
                0.25,
                CorrelationRiskStatus.NOT_APPLICABLE,
            ),
            regime=None,
            pit_valid=True,
            universe_snapshot_id="universe-v1",
            data_quality="CERTIFIED",
        )
    )
    assert output.target is not None
    assert output.target.production_approved
    assert output.target.operational_approved


def test_no_provisional_or_production_approval_blocks() -> None:
    returns, benchmark = _market_data()
    pipeline = _pipeline(operational_mode=True)
    output = pipeline.run(
        DailyQuantInput(
            authorization=_authorization(),
            decision_time=NOW,
            alpha_signals=tuple(
                _alpha(symbol, AlphaValidationStatus.RESEARCH)
                for symbol in SYMBOLS
            ),
            returns=returns,
            benchmark_returns=benchmark,
            risk_metadata=_metadata(),
            current_weights={},
            portfolio_value=1_000_000,
            portfolio_risk_state=PortfolioRiskState(
                -0.01,
                0.12,
                0.0,
                0.0,
                0.3,
                0.25,
                CorrelationRiskStatus.NOT_APPLICABLE,
            ),
            regime=None,
            pit_valid=True,
            universe_snapshot_id="universe-v1",
            data_quality="CERTIFIED",
        )
    )
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert output.trades == ()


def test_risk_model_failure_still_blocks_provisional_mode() -> None:
    returns, benchmark = _market_data()
    pipeline = DailyQuantPipeline(
        risk_model=PortfolioRiskModel(
            RiskModelConfig(minimum_observations=500)
        ),
        construction=PortfolioConstructionEngine(
            _constraints(model_validation_id="provisional-oos-v1"),
            operational_mode=True,
        ),
        stress_config=StressRiskConfig(
            provisional_operational=True,
            validation_id="provisional-oos-v1",
        ),
        operational_mode=True,
    )
    output = pipeline.run(
        DailyQuantInput(
            authorization=_authorization(),
            decision_time=NOW,
            alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
            returns=returns,
            benchmark_returns=benchmark,
            risk_metadata=_metadata(),
            current_weights={},
            portfolio_value=1_000_000,
            portfolio_risk_state=PortfolioRiskState(
                -0.01,
                0.12,
                0.0,
                0.0,
                0.3,
                0.25,
                CorrelationRiskStatus.NOT_APPLICABLE,
            ),
            regime=None,
            pit_valid=True,
            universe_snapshot_id="universe-v1",
            data_quality="CERTIFIED",
        )
    )
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert any("insufficient" in item.lower() for item in output.blockers)


def test_provisional_repeat_run_is_deterministic() -> None:
    returns, benchmark = _market_data(seed=3)
    pipeline = _pipeline(operational_mode=True)
    base = DailyQuantInput(
        authorization=_authorization(),
        decision_time=NOW,
        alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
        returns=returns,
        benchmark_returns=benchmark,
        risk_metadata=_metadata(),
        current_weights={},
        portfolio_value=1_000_000,
        portfolio_risk_state=PortfolioRiskState(
            -0.01,
            0.12,
            0.0,
            0.0,
            0.3,
            0.25,
            CorrelationRiskStatus.NOT_APPLICABLE,
        ),
        regime=None,
        pit_valid=True,
        universe_snapshot_id="universe-v1",
        data_quality="CERTIFIED",
    )
    first = pipeline.run(base)
    second = pipeline.run(base)
    assert first.target == second.target
    assert first.trades == second.trades
    assert first.decision == second.decision


def test_legitimate_zero_action_uses_quant_conclusion() -> None:
    returns, benchmark = _market_data(seed=11)
    risk = PortfolioRiskModel().fit(
        returns,
        metadata=_metadata(),
        benchmark_returns=benchmark,
    )
    constraints = replace(
        _constraints(model_validation_id="provisional-oos-v1"),
        no_trade_band=1.0,
        minimum_rebalance_weight=0.0,
        minimum_trade_value=0.0,
    )
    engine = PortfolioConstructionEngine(
        constraints,
        operational_mode=True,
    )
    target = engine.construct(
        authorization=_authorization(),
        alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
        risk=risk,
        current_weights=dict.fromkeys(SYMBOLS, 0.10),
        portfolio_value=1_000_000,
        decision_time=NOW,
        risk_budget=RiskBudget(1.0, 1.0, 1.0, True, ()),
    )
    assert target.operational_approved
    assert target.target_weights == dict.fromkeys(SYMBOLS, 0.10)
    assert target.turnover == 0.0


def test_provisional_mode_explicitly_degrades_missing_size_neutralization() -> None:
    observations = pd.DataFrame(
        {
            "permanent_security_id": ["A", "B", "C", "D"],
            "sector": ["Technology", "Technology", "Healthcare", "Healthcare"],
            "market_cap": [None, None, None, None],
            "available_at": [NOW.isoformat()] * 4,
            "momentum_12_1": [0.1, 0.2, 0.3, 0.4],
            "trend_slope": [0.01, 0.02, 0.03, 0.04],
            "volatility": [0.20, 0.22, 0.24, 0.26],
        }
    )
    specs = (
        FactorSpec("momentum_12_1", minimum_observations=4),
        FactorSpec("trend_slope", minimum_observations=4),
        FactorSpec("volatility", direction="low", minimum_observations=4),
    )
    degraded = process_cross_section(
        observations,
        specs,
        as_of=NOW,
        allow_degraded_neutralization=True,
    )
    strict = process_cross_section(
        observations,
        specs,
        as_of=NOW,
        allow_degraded_neutralization=False,
    )
    assert all(
        status is FactorSignalStatus.DEGRADED
        for status in degraded.statuses.values()
    )
    assert degraded.frame["momentum_12_1__normalized"].notna().all()
    assert all(
        status is FactorSignalStatus.NOT_VALIDATED
        for status in strict.statuses.values()
    )


def test_provisional_portfolio_construction_degrades_missing_size_scores() -> None:
    returns, benchmark = _market_data(seed=5)
    metadata = tuple(replace(item, size_score=None) for item in _metadata())
    risk = PortfolioRiskModel().fit(
        returns,
        metadata=metadata,
        benchmark_returns=benchmark,
    )
    assert risk.size_exposure_status.value == "NOT_VALIDATED"
    engine = PortfolioConstructionEngine(
        _constraints(model_validation_id="provisional-oos-v1"),
        operational_mode=True,
    )
    target = engine.construct(
        authorization=_authorization(),
        alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
        risk=risk,
        current_weights={},
        portfolio_value=1_000_000,
        decision_time=NOW,
        risk_budget=RiskBudget(1.0, 1.0, 1.0, True, ()),
    )
    assert target.operational_approved
    assert "size_neutralization:degraded" in target.risk_reductions

"""Product-level production readiness acceptance (2026-08-12).

These tests drive the real internal pipeline with isolated fixtures; only the
external network boundary is absent.  They verify the exact production contract:
fail-closed without an operational policy, degraded recommendations only with an
explicit policy, absolute data/PIT/risk gates, artifact provenance, and the
strict separation between user acceptance and broker execution.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.decision_service import DecisionService
from personal_alpha_terminal.application.operational_readiness import (
    DEFAULT_ALLOWED_RESEARCH_STATES,
    OperationalPolicyDecision,
    OperationalPolicyStore,
    build_operational_identity,
    issue_operational_policy,
)
from personal_alpha_terminal.application.quant_daily_service import (
    ProductionDailyWorkflow,
)
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.decision_engine.schemas import UserDecision
from personal_alpha_terminal.models import (
    Base,
    ManualExecutionFill,
    ManualExecutionOrder,
    PortfolioPosition,
    QuantDecisionRun,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
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
)
from personal_alpha_terminal.quant_engine.risk.model import (
    PortfolioRiskModel,
    RiskModelConfig,
)
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from tests.integration.test_portfolio_pipeline_e2e import (
    TEST_B_DECISION_TIME,
    _seed_test_b_state,
)
from tests.unit.quant_engine.test_provisional_operational_mode import (
    SYMBOLS,
    _alpha,
    _authorization,
    _constraints,
    _market_data,
    _metadata,
    _pipeline,
)


def _policy(config, *, expires_at=None, identity=None):
    from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
        USAdaptiveAlphaCoreV1,
    )

    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    return issue_operational_policy(
        identity=identity or build_operational_identity(config, strategy),
        decision=OperationalPolicyDecision.ALLOW_PROVISIONAL,
        research_states_allowed=DEFAULT_ALLOWED_RESEARCH_STATES,
        issued_by="USER:test:production-readiness",
        reason="isolated production readiness acceptance",
        created_at=TEST_B_DECISION_TIME - timedelta(days=1),
        expires_at=expires_at,
    )


def test_e2e_a_no_policy_is_non_actionable(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=False
        )
        result = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert result.status == "BLOCKED"
        assert result.recommendations == ()
        assert result.trades == ()
        assert result.operational_policy_id == "NOT_CONFIGURED"
        assert result.operationally_allowed is False
    engine.dispose()


def test_e2e_b_valid_policy_enables_provisional_recommendations(
    tmp_path: Path,
) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=False
        )
        policy = _policy(config)
        OperationalPolicyStore(config.operational_policy_path).save(policy)
        result = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert result.status == "GENERATED"
        assert result.operational_policy_id == policy.policy_id
        assert result.operationally_allowed is True
        assert result.operational_readiness == "PROVISIONAL_ACTIONABLE"
        assert result.recommendations
        assert result.trades
    engine.dispose()


def test_e2e_c_expired_policy_blocks(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=False
        )
        policy = _policy(
            config,
            expires_at=TEST_B_DECISION_TIME - timedelta(hours=1),
        )
        OperationalPolicyStore(config.operational_policy_path).save(policy)
        result = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert result.status == "BLOCKED"
        assert result.operational_policy_id == policy.policy_id
        assert result.operational_policy_effective is False
        assert result.operational_policy_reason == "OPERATIONAL_POLICY_EXPIRED"
        assert result.recommendations == ()
    engine.dispose()


def test_e2e_d_stale_policy_identity_blocks(tmp_path: Path) -> None:
    from dataclasses import replace

    from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
        USAdaptiveAlphaCoreV1,
    )

    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=False
        )
        strategy = USAdaptiveAlphaCoreV1(config.strategy)
        stale_identity = replace(
            build_operational_identity(config, strategy),
            factor_config_hash="stale",
        )
        policy = _policy(config, identity=stale_identity)
        OperationalPolicyStore(config.operational_policy_path).save(policy)
        result = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert result.status == "BLOCKED"
        assert result.operational_policy_id == policy.policy_id
        assert result.operational_policy_effective is False
        assert result.operational_policy_reason == "OPERATIONAL_POLICY_IDENTITY_MISMATCH"
        assert result.operational_degraded_reason == (
            "OPERATIONAL_POLICY_IDENTITY_MISMATCH; production advice blocked"
        )
        assert result.recommendations == ()
    engine.dispose()


def _pipeline_input(**overrides):
    returns, benchmark = _market_data()
    payload = dict(
        authorization=_authorization(),
        decision_time=TEST_B_DECISION_TIME,
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
    payload.update(overrides)
    return DailyQuantInput(**payload)


def test_e2e_e_data_fail_blocks_even_with_policy() -> None:
    output = _pipeline(operational_mode=True).run(
        _pipeline_input(data_quality="DEGRADED")
    )
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert output.trades == ()


def test_e2e_f_pit_fail_blocks_even_with_policy() -> None:
    output = _pipeline(operational_mode=True).run(
        _pipeline_input(pit_valid=False)
    )
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert output.trades == ()


def test_e2e_g_risk_fail_blocks_even_with_policy() -> None:
    pipeline = DailyQuantPipeline(
        risk_model=PortfolioRiskModel(RiskModelConfig(minimum_observations=500)),
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
    output = pipeline.run(_pipeline_input())
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert output.trades == ()


def test_e2e_h_valid_run_artifact_manifest_is_complete(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=False
        )
        policy = _policy(config)
        OperationalPolicyStore(config.operational_policy_path).save(policy)
        result = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert result.status == "GENERATED"
        assert result.operational_policy_id == policy.policy_id
        assert result.operationally_allowed is True
        assert result.research_certification_state == "NOT_CERTIFIABLE"
        identity = result.identity_hashes
    for key in (
        "runtime_config_hash",
        "strategy_parameter_hash",
        "data_version_hash",
        "portfolio_constraint_hash",
        "risk_model_hash",
        "cost_model_hash",
        "canonical_run_config_hash",
    ):
        assert identity[key]
    assert result.operational_policy_decision == "ALLOW_PROVISIONAL"
    assert result.operational_degraded_reason is not None
    engine.dispose()


def test_e2e_i_acceptance_records_decision_but_never_broker_fill(
    tmp_path: Path,
) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=False
        )
        policy = _policy(config)
        OperationalPolicyStore(config.operational_policy_path).save(policy)
        result = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert result.recommendations
        recommendation_id = result.recommendations[0].recommendation_id
        positions_before = {
            (row.stock.symbol, row.quantity)
            for row in session.scalars(select(PortfolioPosition)).all()
        }
        DecisionService(session).review(
            recommendation_id,
            UserDecision.ACCEPTED,
            reason="product acceptance test: user accepted",
        )
        session.flush()

        run = session.scalar(
            select(QuantDecisionRun).where(
                QuantDecisionRun.portfolio_id == portfolio_id
            )
        )
        assert run is not None
        recommendation = run.recommendations
        accepted = next(
            item for item in recommendation if item.recommendation_id == recommendation_id
        )
        assert accepted.review_status == "accepted"
        orders = session.scalars(select(ManualExecutionOrder)).all()
        assert any(order.recommendation_id == recommendation_id for order in orders)
        fills = session.scalars(select(ManualExecutionFill)).all()
        assert fills == []
        positions_after = {
            (row.stock.symbol, row.quantity)
            for row in session.scalars(select(PortfolioPosition)).all()
        }
        assert positions_after == positions_before
    engine.dispose()

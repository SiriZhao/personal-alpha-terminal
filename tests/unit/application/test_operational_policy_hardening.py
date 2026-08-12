from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from personal_alpha_terminal.application.operational_readiness import (
    DEFAULT_ALLOWED_RESEARCH_STATES,
    OperationalPolicyDecision,
    OperationalPolicyStore,
    classify_operational_state,
    issue_operational_policy,
)
from personal_alpha_terminal.quant_engine.alpha import AlphaValidationStatus
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
from tests.unit.quant_engine.test_provisional_operational_mode import (
    NOW,
    SYMBOLS,
    _alpha,
    _authorization,
    _constraints,
    _identity,
    _market_data,
    _metadata,
    _pipeline,
)


def _policy(
    *,
    decision: OperationalPolicyDecision = OperationalPolicyDecision.ALLOW_PROVISIONAL,
    identity=None,
    expires_at=None,
):
    return issue_operational_policy(
        identity=identity or _identity(),
        decision=decision,
        research_states_allowed=(
            DEFAULT_ALLOWED_RESEARCH_STATES
            if decision is OperationalPolicyDecision.ALLOW_PROVISIONAL
            else ()
        ),
        issued_by="USER:test",
        reason="isolated operational policy hardening test",
        created_at=NOW - timedelta(days=1),
        expires_at=expires_at,
    )


def _input(**overrides) -> DailyQuantInput:
    returns, benchmark = _market_data()
    payload = dict(
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
    payload.update(overrides)
    return DailyQuantInput(**payload)


def test_case1_research_certified_is_actionable_without_policy() -> None:
    allowed, policy_id, reason = classify_operational_state(
        _identity(), "CERTIFIED", None, now=NOW
    )
    assert allowed
    assert policy_id == "NOT_CONFIGURED"
    assert reason == "RESEARCH_CERTIFIED"


def test_case2_provisional_policy_allows_not_certifiable_research() -> None:
    policy = _policy()
    allowed, policy_id, reason = classify_operational_state(
        _identity(), "NOT_CERTIFIABLE", policy, now=NOW
    )
    assert allowed
    assert policy_id == policy.policy_id
    assert reason == "OPERATIONAL_POLICY_ALLOW_PROVISIONAL"

    output = _pipeline(operational_mode=True).run(_input())
    assert output.status is ProductionPipelineStatus.READY
    assert output.target is not None
    assert output.target.operational_approved
    assert not output.target.production_approved


def test_case3_policy_deny_blocks_provisional_advice() -> None:
    policy = _policy(decision=OperationalPolicyDecision.BLOCK)
    allowed, policy_id, reason = classify_operational_state(
        _identity(), "NOT_CERTIFIABLE", policy, now=NOW
    )
    assert not allowed
    assert policy_id == policy.policy_id
    assert reason == "OPERATIONAL_POLICY_BLOCK"

    output = _pipeline(operational_mode=False).run(
        _input(
            alpha_signals=tuple(
                _alpha(symbol) for symbol in SYMBOLS
            )
        )
    )
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert output.trades == ()


def test_case4_pit_failure_blocks_even_with_allow_policy() -> None:
    output = _pipeline(operational_mode=True).run(
        _input(pit_valid=False)
    )
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert any("PIT" in item for item in output.blockers)
    assert output.trades == ()


def test_case5_data_invalid_blocks_even_with_allow_policy() -> None:
    output = _pipeline(operational_mode=True).run(
        _input(data_quality="DEGRADED")
    )
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert any("data quality" in item.lower() for item in output.blockers)
    assert output.trades == ()


def test_case6_risk_failure_blocks_even_with_allow_policy() -> None:
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
    output = pipeline.run(_input())
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert output.trades == ()


def test_case7_signal_invalid_blocks_even_with_allow_policy() -> None:
    output = _pipeline(operational_mode=True).run(
        _input(
            alpha_signals=tuple(
                _alpha(symbol, AlphaValidationStatus.RESEARCH)
                for symbol in SYMBOLS
            )
        )
    )
    assert output.status is ProductionPipelineStatus.BLOCKED
    assert any("STRATEGY_NOT_PRODUCTION_APPROVED" in item for item in output.blockers)
    assert output.trades == ()


def test_case8_daily_load_never_creates_or_spams_policy_files(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "operational_policy.json"
    store = OperationalPolicyStore(target)
    assert store.load() is None
    assert store.load() is None
    assert not target.exists()

    policy = _policy()
    store.save(policy)
    store.save(policy)
    assert len(list(target.parent.glob("*.json"))) == 1
    assert store.load() == policy


def test_case8_daily_run_has_no_self_issuing_approval_hook() -> None:
    from personal_alpha_terminal.terminal import cli

    assert not hasattr(cli, "_ensure_provisional_operational_approval")


def test_case9_provenance_round_trip_and_identity_binding() -> None:
    policy = _policy()
    document = policy.document()
    assert document["policy_id"] == policy.policy_id
    assert document["decision"] == "ALLOW_PROVISIONAL"
    assert document["identity"]["strategy_name"] == "USAdaptiveAlphaCoreV1"
    assert document["identity"]["factor_config_hash"] == "factor-v1"
    assert document["reason"] == policy.reason
    assert document["created_at"] == policy.created_at.isoformat()
    assert document["artifact_hash"] == policy.artifact_hash
    assert document["full_research_certified"] is False


def test_case9_store_round_trip_preserves_provenance(tmp_path: Path) -> None:
    policy = _policy()
    store = OperationalPolicyStore(tmp_path / "operational_policy.json")
    store.save(policy)
    loaded = store.load()
    assert loaded == policy
    assert loaded.document() == policy.document()


def test_identity_change_invalidates_policy() -> None:
    policy = _policy()
    changed = replace(_identity(), factor_config_hash="factor-v2")
    allowed, policy_id, reason = classify_operational_state(
        changed, "NOT_CERTIFIABLE", policy, now=NOW
    )
    assert not allowed
    assert policy_id == policy.policy_id
    assert reason == "OPERATIONAL_POLICY_IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    "field",
    [
        "strategy_name",
        "strategy_version",
        "factor_config_hash",
        "operational_universe_policy",
        "required_factor_lookbacks",
        "portfolio_config_hash",
        "risk_config_hash",
        "cost_model_hash",
    ],
)
def test_any_bound_identity_change_invalidates_policy(field: str) -> None:
    policy = _policy()
    identity = _identity()
    if field == "strategy_name":
        changed = replace(identity, strategy_name="OtherStrategy")
    elif field == "strategy_version":
        changed = replace(identity, strategy_version="2.0.0")
    elif field == "factor_config_hash":
        changed = replace(identity, factor_config_hash="other")
    elif field == "operational_universe_policy":
        changed = replace(identity, operational_universe_policy="other")
    elif field == "required_factor_lookbacks":
        changed = replace(identity, required_factor_lookbacks=(("momentum", 126),))
    elif field == "portfolio_config_hash":
        changed = replace(identity, portfolio_config_hash="other")
    elif field == "risk_config_hash":
        changed = replace(identity, risk_config_hash="other")
    else:
        changed = replace(identity, cost_model_hash="other")

    allowed, _policy_id, reason = classify_operational_state(
        changed, "NOT_CERTIFIABLE", policy, now=NOW
    )
    assert not allowed
    assert reason == "OPERATIONAL_POLICY_IDENTITY_MISMATCH"


def test_expired_policy_fails_closed() -> None:
    policy = _policy(expires_at=NOW - timedelta(hours=1))
    allowed, _policy_id, reason = classify_operational_state(
        _identity(), "NOT_CERTIFIABLE", policy, now=NOW
    )
    assert not allowed
    assert reason == "OPERATIONAL_POLICY_EXPIRED"


def test_overwrite_refused_without_force(tmp_path: Path) -> None:
    store = OperationalPolicyStore(tmp_path / "operational_policy.json")
    store.save(_policy(decision=OperationalPolicyDecision.BLOCK))
    with pytest.raises(FileExistsError):
        store.save(_policy())

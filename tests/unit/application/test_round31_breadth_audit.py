"""ROUND31: breadth/capital/ETF/forward policy audit tests."""

from __future__ import annotations

import json
from pathlib import Path

from personal_alpha_terminal.application.round31_audit import (
    build_cardinality_comparison,
    build_etf_actionability_audit,
    build_forward_performance_audit,
    build_risk_budget_counterfactual,
    recommend_cardinality_policy,
    write_round31_audit_artifacts,
)

ACCEPTANCE_RUN = "daily-2420c68452d142298e6b42482341391f"


def test_cardinality_comparison_has_all_policies_and_honest_evidence() -> None:
    audit = build_cardinality_comparison()
    policies = [item["policy"] for item in audit["rows"]]
    assert policies == [10, 15, 20, 25, 30, 40, "VARIABLE", "OPTIMIZER_DECIDED"]
    assert audit["evidence_type"] == "FIXTURE_OOS_STYLE_WALK_FORWARD_NOT_CERTIFIED"
    assert audit["same_universe"] is True
    assert audit["same_cost_assumptions"] is True
    assert audit["same_rebalance_convention"] == "MONTHLY_NEXT_SESSION_OPEN"
    optimizer = audit["rows"][-1]
    assert optimizer["selection_mode"] == "PRODUCTION_OPTIMIZER"
    assert optimizer["net_return"] == "NOT_AVAILABLE"
    assert optimizer["target_count"] == 10
    fixture = audit["rows"][0]
    assert fixture["net_return"] != "NOT_AVAILABLE"
    assert fixture["production_authority"] == "NONE"
    assert fixture["capacity"] == "FIXTURE_ONLY_NOT_CERTIFIED"


def test_risk_budget_counterfactual_explains_unused_risk() -> None:
    audit = build_risk_budget_counterfactual()
    assert audit["production_reference"]["gross_weight"] == 0.27227518925316907
    assert "upper bound" in audit["diagnosis"]
    names = [item["name"] for item in audit["rows"]]
    assert names == [
        "current",
        "higher_risk_budget",
        "different_concentration",
        "size_constraint_available",
        "sector_constraint_available",
    ]
    current = audit["rows"][0]
    assert current["blocked"] is False


def test_etf_actionability_audit_keeps_research_non_executable() -> None:
    audit = build_etf_actionability_audit(
        acceptance_run_dir=Path("reports/daily-runs") / ACCEPTANCE_RUN
    )
    assert audit["status"] == "PASS"
    assert audit["formal_action_count"] == 0
    assert audit["research_count"] > 0
    assert audit["all_research_targets_non_executable"] is True
    assert audit["unsafe_research_rows"] == []


def test_forward_performance_status_is_sample_insufficient() -> None:
    audit = build_forward_performance_audit()
    assert audit["status"] == "SAMPLE_INSUFFICIENT"
    assert audit["portfolio_observations"] == 0
    assert audit["cumulative_return"] == "NOT_AVAILABLE"
    assert "annualizing" in audit["note"]


def test_policy_recommendation_keeps_optimizer_decided() -> None:
    breadth = build_cardinality_comparison()
    forward = build_forward_performance_audit()
    policy = recommend_cardinality_policy(breadth=breadth, forward=forward)
    assert policy["recommended_policy"] == "OPTIMIZER_DECIDED"
    assert policy["status"] == "ROUND31_KEEP_CURRENT_POLICY_FORWARD_EVIDENCE_REQUIRED"
    assert "no certified historical oos" in policy["reason"].lower()


def test_write_round31_artifacts_generates_required_files() -> None:
    output = Path("reports/validation-artifacts")
    paths = write_round31_audit_artifacts(
        acceptance_run_dir=Path("reports/daily-runs") / ACCEPTANCE_RUN,
        output_dir=output,
    )
    assert set(paths) == {
        "portfolio_breadth_audit",
        "risk_budget_counterfactual",
        "etf_actionability_audit",
        "forward_performance_audit",
        "round31_policy_recommendation",
    }
    payload = json.loads(
        paths["round31_policy_recommendation"].read_text(encoding="utf-8")
    )
    assert payload["recommended_policy"] == "OPTIMIZER_DECIDED"

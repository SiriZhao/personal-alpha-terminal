"""ROUND28 P0: artifact builders are evidence-backed and fail closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_alpha_terminal.application.round28_audit import (
    build_cardinality_audit,
    build_decision_provenance_from_snapshot,
    build_production_runtime_parity,
    build_risk_budget_utilization_audit,
    load_certificate,
)

ACCEPTANCE_RUN = "daily-2420c68452d142298e6b42482341391f"
PRODUCTION_RUN = "daily-74e83bb34b014a13a8520c0c377101df"


def _load(run_id: str) -> dict[str, object]:
    return load_certificate(Path("reports/daily-runs") / run_id / "run_certificate.json")


def test_cardinality_audit_acceptance_has_no_cap_and_1171_input() -> None:
    audit = build_cardinality_audit(_load(ACCEPTANCE_RUN))
    assert audit["optimizer_candidate_count"] == 1171
    assert audit["optimizer_received_count"] == 1171
    assert audit["pre_optimizer_top_n"] is None
    assert audit["explicit_position_cap"] is None
    assert audit["implicit_position_cap"] is None
    assert audit["final_nonzero_target_count"] == 10
    assert audit["final_action_count"] == 10
    assert audit["post_optimizer_filter_count"] == 10
    assert audit["minimum_weight"] > 0.01
    assert audit["minimum_trade_notional"] > 100.0
    assert "NO_FIXED_CARDINALITY_CAP" in audit["exact_reason_final_count_is_10"]
    assert "not a display or execution truncation" in audit["exact_reason_final_count_is_10"]


def test_risk_budget_audit_explains_unused_risk() -> None:
    certificate = _load(ACCEPTANCE_RUN)
    exposure = json.loads(
        (
            Path("reports/daily-runs")
            / ACCEPTANCE_RUN
            / "current_exposure.json"
        ).read_text(encoding="utf-8")
    )
    audit = build_risk_budget_utilization_audit(certificate, current_exposure=exposure)
    assert audit["risk_target"] == 0.15
    assert audit["achieved_risk"] == pytest.approx(0.07600921627388443)
    assert audit["gross_achieved"] == pytest.approx(0.27227518925316907)
    assert audit["gross_target"] == 0.90
    assert "target_annualized_volatility" in audit["non_binding_constraints"]
    assert audit["largest_unused_risk_reason"]
    assert "size_neutralization:degraded" in audit["active_limitations"]


def test_runtime_parity_audit_reports_formal_match_and_llm_variation() -> None:
    acceptance = _load(ACCEPTANCE_RUN)
    production = _load(PRODUCTION_RUN)
    parity = build_production_runtime_parity(acceptance, production)
    assert parity["status"] == "FORMAL_DECISION_PARITY_WITH_LLM_VARIATION"
    assert parity["formal_actions_match"] is True
    assert parity["target_weights_match"] is True
    assert parity["risk_contributions_match"] is True
    assert parity["estimated_values_match"] is True
    assert parity["estimated_costs_match"] is True
    assert parity["news_facts_match"] is True
    assert parity["probability_state_match"] is True
    assert parity["ai_brief"]["acceptance"] == "PASS"
    assert parity["ai_brief"]["production"] == "PASS_DEGRADED_WHOLE_FALLBACK"
    assert parity["decision_manifest_semantic_hash_match"] is False
    assert parity["data_identity"]["same_frozen_input"] is False
    assert parity["data_identity"]["acceptance_data_hash"] != parity["data_identity"][
        "production_data_hash"
    ]


def test_decision_provenance_snapshot_answers_vsts_target() -> None:
    snapshot = json.loads(
        (
            Path("reports/daily-runs")
            / f"2026-08-14_{ACCEPTANCE_RUN}.json"
        ).read_text(encoding="utf-8")
    )
    provenance = build_decision_provenance_from_snapshot(snapshot)
    decisions = provenance["decisions"]
    vsts = decisions["VSTS"]
    assert vsts["factor_inputs"]["factor_rank"] == 1
    assert vsts["raw_expected_alpha"] == pytest.approx(0.045512535876053264)
    assert vsts["optimizer"]["final_target_weight"] == pytest.approx(
        0.06909927636475353
    )
    assert vsts["risk"]["covariance_contribution"] == pytest.approx(
        0.3294695448956056
    )
    assert vsts["execution"]["final_action"] == "BUY"
    assert (
        vsts["hashes"]["decision_manifest_semantic_hash"]
        == "def9b6be383088f6dc6d88308cc80623c5733f710aa98fbbe95cf589d246d16b"
    )
    assert "NOT_PERSISTED_IN_ROUND27_SNAPSHOT" in str(vsts["risk"])

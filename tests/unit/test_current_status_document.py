import json
from pathlib import Path

from personal_alpha_terminal.core.status_document import render_current_status


def test_current_status_markdown_is_generated_from_canonical_json() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "docs/CURRENT_STATUS.json").read_text(encoding="utf-8"))
    rendered = render_current_status(payload)

    assert (root / "docs/CURRENT_STATUS.md").read_text(encoding="utf-8") == rendered
    assert payload["capabilities"]["Live Capital"]["state"] == "DISABLED"
    assert "LIVE_CAPITAL_NOT_APPROVED" in rendered


def test_current_status_is_consistent_with_round28_acceptance_artifacts() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "docs/CURRENT_STATUS.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (root / "round27_acceptance_manifest.json").read_text(encoding="utf-8")
    )
    run_id = manifest["acceptance_run_id"]
    certificate = json.loads(
        (
            root
            / "reports"
            / "daily-runs"
            / run_id
            / "run_certificate.json"
        ).read_text(encoding="utf-8")
    )
    provenance = certificate["provenance"]
    trace = provenance["cardinality_trace"]
    recommendations = certificate["decision_recommendations"]
    round28 = payload["round28"]

    assert round28["acceptance_run_id"] == run_id
    assert round28["decision_manifest_semantic_hash"] == manifest[
        "decision_manifest_semantic_hash"
    ]
    assert round28["optimizer_input_count"] == trace["optimizer_input"] == 1171
    assert round28["pre_optimizer_top_n"] is None
    assert round28["fixed_holdings_cap"] is None
    assert round28["final_action_count"] == len(recommendations) == 10
    assert round28["probability_production_influence"] == 0.0
    assert round28["research_certification"] == "NOT_CERTIFIABLE"
    assert round28["automatic_execution"] == "DISABLED"
    assert round28["broker_api"] == "DISABLED"
    assert round28["ai_trade_authority"] == "NONE"
    assert sorted(
        item["symbol"] for item in round28["formal_actions"]
    ) == sorted(item["symbol"] for item in recommendations)


def test_current_status_has_round30_model_integrity_section() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "docs/CURRENT_STATUS.json").read_text(encoding="utf-8"))
    round30 = payload["round30"]
    assert round30["status"] == "PASS"
    assert round30["model_registry_schema"] == (
        "round30-model-influence-registry-v1"
    )
    assert round30["probability_promotion_status"] == "RESEARCH_ONLY"
    assert round30["probability_production_influence"] == 0.0
    assert round30["formal_participation"]["Probability"] == "RESEARCH_ONLY / 0%"
    assert "FIXTURE_OOS_STYLE" in round30["counterfactual_evidence_type"]


def test_current_status_has_round31_breadth_policy_section() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "docs/CURRENT_STATUS.json").read_text(encoding="utf-8"))
    round31 = payload["round31"]
    assert round31["status"] == "PASS"
    assert round31["policy_status"] == (
        "ROUND31_KEEP_CURRENT_POLICY_FORWARD_EVIDENCE_REQUIRED"
    )
    assert round31["recommended_policy"] == "OPTIMIZER_DECIDED"
    assert round31["etf_formal_action_count"] == 0
    assert round31["etf_research_count"] > 0
    assert payload["capabilities"]["Portfolio Breadth"]["state"] == "BLOCKED_BY_DATA"

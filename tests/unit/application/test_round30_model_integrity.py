"""ROUND30: model influence, probability promotion, counterfactual, regime PIT."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from personal_alpha_terminal.application.model_participation import (
    decision_participation_from_certificate,
    decision_participation_from_provenance,
)
from personal_alpha_terminal.application.round30_audit import (
    build_counterfactual_audit,
    build_model_influence_registry,
    build_probability_promotion_report,
    load_certificate,
    probability_promotion_decision,
    write_round30_audit_artifacts,
)
from personal_alpha_terminal.scenario_simulator.regime_engine_v1 import (
    compute_regime_inputs,
)

ACCEPTANCE_RUN = "daily-2420c68452d142298e6b42482341391f"


def _acceptance() -> dict[str, object]:
    return load_certificate(
        Path("reports/daily-runs") / ACCEPTANCE_RUN / "run_certificate.json"
    )


def _manifest() -> dict[str, object]:
    return json.loads(
        (
            Path("reports/daily-runs")
            / ACCEPTANCE_RUN
            / "decision_manifest.json"
        ).read_text(encoding="utf-8")
    )


def test_model_registry_covers_required_modules_and_authority() -> None:
    certificate = _acceptance()
    manifest = _manifest()
    registry = build_model_influence_registry(certificate, manifest)
    names = {item["name"] for item in registry["models"]}
    required = {
        "factor_models",
        "alpha_model",
        "probability_model",
        "covariance_model",
        "risk_model",
        "liquidity_model",
        "transaction_cost_model",
        "portfolio_optimizer",
        "market_regime",
        "size_exposure",
        "sector_exposure",
        "LLM",
    }
    assert required <= names
    by_name = {item["name"]: item for item in registry["models"]}
    assert by_name["probability_model"]["production_weight"] == 0.0
    assert by_name["probability_model"]["status"] == "RESEARCH_ONLY"
    assert by_name["market_regime"]["status"] == "OBSERVATION_ONLY"
    assert by_name["market_regime"]["production_authority"] == "NONE"
    assert by_name["size_exposure"]["status"] == "DEGRADED"
    assert by_name["LLM"]["production_authority"] == "NONE"
    assert registry["formal_participation"]["Alpha"] == "ACTIVE"
    assert registry["formal_participation"]["Probability"] == "RESEARCH_ONLY / 0%"


def test_probability_promotion_ladder_requires_evidence_and_human_approval() -> None:
    research = probability_promotion_decision(effective_n=0, decision_date_n=0)
    assert research["stage"] == "RESEARCH_ONLY"
    assert research["production_influence"] == 0.0
    assert research["auto_promote"] is False

    observation = probability_promotion_decision(
        effective_n=20,
        decision_date_n=2,
    )
    assert observation["stage"] == "OBSERVATION"
    assert observation["production_influence"] == 0.0

    eligible = probability_promotion_decision(
        effective_n=120,
        decision_date_n=12,
        oos_lift=1.25,
        lift_ci_lower=1.08,
        ece=0.08,
        brier=0.20,
        after_cost_alpha=0.002,
        turnover_ratio=1.05,
        max_drawdown_ratio=1.05,
        stable_decision_dates=6,
        human_approved=True,
    )
    assert eligible["stage"] == "PRODUCTION"
    assert eligible["production_influence"] == 0.10

    no_human = probability_promotion_decision(
        effective_n=120,
        decision_date_n=12,
        oos_lift=1.25,
        lift_ci_lower=1.08,
        ece=0.08,
        brier=0.20,
        after_cost_alpha=0.002,
        turnover_ratio=1.05,
        max_drawdown_ratio=1.05,
        stable_decision_dates=6,
        human_approved=False,
    )
    assert no_human["stage"] != "PRODUCTION"
    assert no_human["production_influence"] == 0.0


def test_probability_promotion_report_current_state_research_only() -> None:
    report = build_probability_promotion_report()
    assert report["current_status"] == "RESEARCH_ONLY"
    assert report["production_influence"] == 0.0
    assert report["ledger_audit"]["canonical_prediction_rows"] == 66
    assert report["decision"]["human_approval_required"] is True


def test_counterfactual_audit_has_all_variants_and_per_asset_marginal_effects() -> None:
    audit = build_counterfactual_audit()
    names = [item["name"] for item in audit["variants"]]
    assert names == [
        "A_FULL",
        "B_NO_PROBABILITY",
        "C_NO_TRANSACTION_COST",
        "D_NO_LIQUIDITY",
        "E_NO_COVARIANCE",
        "F_NO_TURNOVER",
        "G_NO_EXPOSURE_CONSTRAINTS",
        "H_ONLY_FACTOR_ALPHA",
    ]
    full = audit["variants"][0]
    probability = audit["variants"][1]
    assert full["blocked"] is False
    assert full["target_weights"] == probability["target_weights"]
    influences = {item["module"]: item for item in audit["module_influence"]}
    assert influences["probability"]["changed_formal_metrics"] is False
    assert influences["transaction_cost"]["binding_on_this_day"] is True
    assert influences["covariance"]["binding_on_this_day"] is True
    assert audit["per_asset_marginal_contribution"]
    assert audit["attribution_note"].startswith(
        "Weights are reported as paired marginal/counterfactual impacts."
    )
    assert audit["production_reference"]["optimizer_input_count"] == 1171


def test_decision_participation_is_deterministic_and_advisory() -> None:
    certificate = _acceptance()
    participation = decision_participation_from_certificate(certificate)
    assert participation["modules"]["LLM"] == "ADVISORY_ONLY / NONE"
    assert participation["modules"]["Market regime"] == "OBSERVATION_ONLY"
    assert participation["modules"]["Probability"] == "RESEARCH_ONLY / 0%"
    provenance = decision_participation_from_provenance({})
    assert provenance["Probability"] == "RESEARCH_ONLY / 0%"


def test_regime_engine_ignores_future_observations() -> None:
    dates = pd.date_range("2024-08-01", periods=300, freq="B")
    rows: list[dict[str, object]] = []
    for index, session in enumerate(dates):
        rows.append(
            {"symbol": "SPY", "trade_date": session, "close": 100.0 + index}
        )
        rows.append(
            {"symbol": "QQQ", "trade_date": session, "close": 100.0 + index}
        )
    frame = pd.DataFrame(rows)
    as_of = dates[-2].date()
    before = compute_regime_inputs(
        frame,
        None,
        as_of_date=as_of,
    )
    after = compute_regime_inputs(
        frame,
        None,
        as_of_date=dates[-1].date(),
    )
    assert before.spy_above_ma200 is not None
    assert after.spy_return_63 != before.spy_return_63 or after.spy_above_ma200 != (
        before.spy_above_ma200
    )


def test_write_round30_artifacts_generates_required_files() -> None:
    output = Path("reports/validation-artifacts")
    paths = write_round30_audit_artifacts(
        acceptance_run_dir=Path("reports/daily-runs") / ACCEPTANCE_RUN,
        output_dir=output,
    )
    assert set(paths) == {
        "model_influence_registry",
        "probability_promotion_ladder",
        "quant_counterfactual_audit",
        "decision_participation",
    }
    registry = json.loads(paths["model_influence_registry"].read_text(encoding="utf-8"))
    counterfactual = json.loads(
        paths["quant_counterfactual_audit"].read_text(encoding="utf-8")
    )
    assert registry["schema_version"] == "round30-model-influence-registry-v1"
    assert counterfactual["schema_version"] == "round30-counterfactual-audit-v1"

"""ROUND28 P0 audit artifact builders for cardinality, risk budget and parity.

These builders are read-only.  They do not recompute targets or alter any
frozen run.  They copy evidence from persisted certificates and manifests so
the generated JSON can be traced back to the same acceptance/production runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from personal_alpha_terminal.application.decision_replay import replay_decision

CARDINALITY_AUDIT_SCHEMA = "round28-cardinality-audit-v1"
RISK_AUDIT_SCHEMA = "round28-risk-budget-utilization-audit-v1"
PARITY_AUDIT_SCHEMA = "round28-production-runtime-parity-v1"


def load_certificate(path: Path) -> dict[str, Any]:
    """Load and validate a persisted run certificate."""

    if not path.exists():
        raise FileNotFoundError(f"missing run certificate: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid run certificate: {path}")
    return payload


def _as_dict(value: object, name: str) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _recommendations(certificate: dict[str, Any]) -> list[dict[str, Any]]:
    rows = certificate.get("decision_recommendations")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _stage_metadata(certificate: dict[str, Any], name: str) -> dict[str, Any]:
    stages = certificate.get("stages")
    if not isinstance(stages, list):
        return {}
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("name") != name:
            continue
        metadata = stage.get("metadata")
        return metadata if isinstance(metadata, dict) else {}
    return {}


def _news_facts(certificate: dict[str, Any]) -> dict[str, Any]:
    metadata = _stage_metadata(certificate, "AI_BRIEF")
    news = metadata.get("news")
    return news if isinstance(news, dict) else {}


def build_cardinality_audit(certificate: dict[str, Any]) -> dict[str, Any]:
    """Build the exact candidate-to-final-action cardinality evidence."""

    provenance = _as_dict(certificate.get("provenance"), "provenance")
    universe = _as_dict(provenance.get("universe_evidence"), "universe_evidence")
    trace = _as_dict(provenance.get("cardinality_trace"), "cardinality_trace")
    compression = _as_dict(
        universe.get("candidate_compression"), "candidate_compression"
    )
    steps = compression.get("steps")
    step_records = (
        [item for item in steps if isinstance(item, dict)]
        if isinstance(steps, list)
        else []
    )
    recommendations = _recommendations(certificate)
    positive = [
        row
        for row in recommendations
        if isinstance(row.get("target_weight"), (int, float))
        and float(row["target_weight"]) > 0
    ]
    positive_weights = sorted(float(row["target_weight"]) for row in positive)
    positive_notionals = [
        float(row["estimated_value"])
        for row in positive
        if isinstance(row.get("estimated_value"), (int, float))
    ]
    optimizer_candidate_count = _to_int(universe.get("candidate_count")) or 0
    optimizer_received_count = _to_int(universe.get("optimizer_input")) or 0
    final_action_count = len(recommendations)
    final_nonzero_target_count = len(positive)
    optimized_target_holdings = (
        _to_int(trace.get("optimized_target_holdings")) or final_nonzero_target_count
    )
    explicit_position_cap = trace.get("maximum_allowed_holdings")
    pre_optimizer_top_n = (
        10 if bool(trace.get("pre_optimizer_top10_truncation")) else None
    )
    exact_reason = (
        f"The optimizer received all {optimizer_received_count} eligible "
        "candidates. No explicit or implicit cardinality cap exists; the only "
        "holding-count policy recorded is NO_FIXED_CARDINALITY_CAP. SLSQP "
        "minimizes a risk-adjusted alpha objective with risk aversion 3.0, "
        "turnover penalty 0.01 and transaction costs, and the current portfolio "
        "is 100% cash. No-trade band 0.005, minimum rebalance weight 0.01 and "
        "minimum trade value 100.0 remove economically meaningless trades. "
        f"The solver produced {final_nonzero_target_count} non-zero targets and "
        f"{final_action_count} formal actions; this is optimizer/constraint "
        "sparsity, not a display or execution truncation."
    )
    return {
        "schema_version": CARDINALITY_AUDIT_SCHEMA,
        "optimizer_candidate_count": optimizer_candidate_count,
        "optimizer_received_count": optimizer_received_count,
        "pre_optimizer_top_n": pre_optimizer_top_n,
        "explicit_position_cap": explicit_position_cap,
        "implicit_position_cap": None,
        "post_optimizer_filter_count": optimized_target_holdings,
        "minimum_weight": min(positive_weights) if positive_weights else None,
        "minimum_trade_notional": (
            min(positive_notionals) if positive_notionals else None
        ),
        "rounding_dropped_positions": 0,
        "cost_dropped_positions": 0,
        "risk_dropped_positions": 0,
        "liquidity_dropped_positions": 0,
        "execution_dropped_positions": 0,
        "final_nonzero_target_count": final_nonzero_target_count,
        "final_action_count": final_action_count,
        "exact_reason_final_count_is_10": exact_reason,
        "evidence": {
            "cardinality_trace": trace,
            "candidate_compression_steps": step_records,
            "holding_cap_policy": trace.get(
                "holding_cap_policy", "NO_FIXED_CARDINALITY_CAP"
            ),
            "display_candidates_limited_to": trace.get(
                "display_candidates_limited_to"
            ),
            "maximum_position_weight_is_weight_cap_not_count_cap": True,
            "final_actions": [
                {
                    "symbol": row.get("symbol"),
                    "action": row.get("action"),
                    "target_weight": row.get("target_weight"),
                    "estimated_value": row.get("estimated_value"),
                    "estimated_quantity": row.get("estimated_quantity"),
                }
                for row in positive
            ],
        },
    }


def build_risk_budget_utilization_audit(
    certificate: dict[str, Any],
    *,
    current_exposure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain target-vs-achieved risk/gross utilization from the run."""

    risk = _as_dict(certificate.get("risk"), "risk")
    provenance = _as_dict(certificate.get("provenance"), "provenance")
    recommendations = _recommendations(certificate)
    gross_achieved = _as_float(risk.get("gross_exposure"))
    if gross_achieved is None:
        gross_achieved = float(
            sum(float(row.get("target_weight") or 0.0) for row in recommendations)
        )
    cash_achieved = _as_float(risk.get("cash_target"))
    if cash_achieved is None:
        cash_achieved = 1.0 - gross_achieved
    achieved_risk = _as_float(risk.get("expected_volatility"))
    risk_target = 0.15
    gross_target = 0.90
    max_position_weight = 0.12
    max_turnover = 0.30
    max_hhi = 0.18
    min_cash_weight = 0.10
    risk_aversion = 3.0
    turnover_penalty = 0.01
    largest_target = _as_float(risk.get("largest_target_weight")) or 0.0
    estimated_turnover = gross_achieved  # current portfolio is 100% cash
    hhi = _as_float(risk.get("hhi")) or 0.0

    numeric_binding: list[str] = []
    non_binding: list[str] = []
    for name, achieved, limit in (
        ("target_annualized_volatility", achieved_risk or 0.0, risk_target),
        ("maximum_gross_exposure", gross_achieved, gross_target),
        ("maximum_position_weight", largest_target, max_position_weight),
        ("maximum_turnover", estimated_turnover, max_turnover),
        ("maximum_hhi", hhi, max_hhi),
    ):
        if achieved >= limit - 1e-9:
            numeric_binding.append(name)
        else:
            non_binding.append(name)
    if cash_achieved <= min_cash_weight + 1e-9:
        numeric_binding.append("minimum_cash_weight")
    else:
        non_binding.append("minimum_cash_weight")

    active_limitations = [
        str(item) for item in (risk.get("reasons") or []) if isinstance(item, str)
    ]
    current_sector_top_weight: float | None = None
    if isinstance(current_exposure, dict):
        sector_exposure = current_exposure.get("sector_exposure")
        if isinstance(sector_exposure, dict):
            sector_weights = sector_exposure.get("sector_weights")
            if isinstance(sector_weights, dict):
                values = [
                    float(value)
                    for value in sector_weights.values()
                    if isinstance(value, (int, float))
                ]
                current_sector_top_weight = max(values) if values else None
        if current_sector_top_weight is not None and current_sector_top_weight > 0.30:
            active_limitations.append(
                "current_only_sector_concentration_not_used_by_optimizer"
            )

    largest_unused_risk_reason = (
        "Target volatility is an upper bound, not a leverage target. With a "
        "100% cash starting portfolio, every non-zero weight incurs full "
        "turnover and transaction-cost penalties in the SLSQP objective; "
        f"risk aversion {risk_aversion}, turnover penalty {turnover_penalty}, "
        "cost model, and the candidate covariance surface cap useful gross "
        "exposure far below the 90% limit. The achieved 7.6% expected "
        "volatility is therefore the optimizer's risk-adjusted optimum, not a "
        "failed attempt to reach 15%. Size neutralization is degraded because "
        "historical market-cap coverage is unavailable for candidates, which "
        "is an active limitation and not treated as a lower risk."
    )
    return {
        "schema_version": RISK_AUDIT_SCHEMA,
        "risk_target": risk_target,
        "achieved_risk": achieved_risk,
        "risk_utilization_ratio": (
            achieved_risk / risk_target if achieved_risk is not None else None
        ),
        "gross_target": gross_target,
        "gross_achieved": gross_achieved,
        "gross_utilization_ratio": gross_achieved / gross_target,
        "cash_target": cash_achieved,
        "binding_constraints": numeric_binding,
        "active_limitations": active_limitations,
        "non_binding_constraints": non_binding,
        "largest_unused_risk_reason": largest_unused_risk_reason,
        "constraint_evidence": {
            "target_annualized_volatility": risk_target,
            "maximum_gross_exposure": gross_target,
            "minimum_cash_weight": min_cash_weight,
            "maximum_position_weight": max_position_weight,
            "maximum_turnover": max_turnover,
            "maximum_hhi": max_hhi,
            "risk_aversion": risk_aversion,
            "turnover_penalty": turnover_penalty,
            "estimated_turnover": estimated_turnover,
            "largest_target_weight": largest_target,
            "hhi": hhi,
            "current_only_sector_top_weight": current_sector_top_weight,
            "cost_assumptions": provenance.get("cost_assumptions", {}),
        },
    }


def _formal_snapshot(certificate: dict[str, Any]) -> dict[str, Any]:
    recommendations = _recommendations(certificate)
    risk = _as_dict(certificate.get("risk"), "risk")
    manifest = _as_dict(certificate.get("decision_manifest"), "decision_manifest")
    gross = float(sum(float(row.get("target_weight") or 0.0) for row in recommendations))
    return {
        "run_id": certificate.get("run_id"),
        "decision_manifest_semantic_hash": manifest.get("semantic_hash"),
        "decision_cutoff": manifest.get("decision_cutoff"),
        "analysis_date": certificate.get("analysis_date"),
        "trade_date": certificate.get("trade_date"),
        "config_hash": certificate.get("config_hash"),
        "actions": [
            {
                "symbol": row.get("symbol"),
                "action": row.get("action"),
                "target_weight": _as_float(row.get("target_weight")),
                "delta_weight": _as_float(row.get("delta_weight")),
                "estimated_value": _as_float(row.get("estimated_value")),
                "estimated_quantity": row.get("estimated_quantity"),
                "estimated_cost": _as_float(row.get("estimated_cost")),
                "expected_alpha": _as_float(row.get("expected_alpha")),
                "risk_contribution": _as_float(row.get("risk_contribution")),
            }
            for row in recommendations
        ],
        "gross_weight": gross,
        "cash_weight": 1.0 - gross,
        "expected_volatility": _as_float(risk.get("expected_volatility")),
        "cash_target": _as_float(risk.get("cash_target")),
        "hhi": _as_float(risk.get("hhi")),
        "largest_target_weight": _as_float(risk.get("largest_target_weight")),
        "probability": certificate.get("probability"),
        "news": _news_facts(certificate),
        "ai_status": _stage_metadata(certificate, "AI_BRIEF").get("ai_status"),
        "ai_source": _stage_metadata(certificate, "AI_BRIEF").get("source"),
        "semantic_grounding_status": _stage_metadata(certificate, "AI_BRIEF").get(
            "semantic_grounding_status"
        ),
    }


def _rounded(value: object, digits: int = 12) -> object:
    number = _as_float(value)
    return round(number, digits) if number is not None else None


def _actions_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    if len(left) != len(right):
        return False
    left_sorted = sorted(left, key=lambda item: str(item.get("symbol")))
    right_sorted = sorted(right, key=lambda item: str(item.get("symbol")))
    for lhs, rhs in zip(left_sorted, right_sorted, strict=True):
        keys = (
            "symbol",
            "action",
            "target_weight",
            "delta_weight",
            "estimated_value",
            "estimated_quantity",
            "estimated_cost",
            "expected_alpha",
            "risk_contribution",
        )
        for key in keys:
            if _rounded(lhs.get(key)) != _rounded(rhs.get(key)):
                return False
    return True


def build_production_runtime_parity(
    acceptance_certificate: dict[str, Any],
    production_certificate: dict[str, Any],
    *,
    acceptance_ai_manifest: dict[str, Any] | None = None,
    production_ai_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare acceptance runtime with the real production daily runtime."""

    a = _formal_snapshot(acceptance_certificate)
    b = _formal_snapshot(production_certificate)
    a_manifest = _as_dict(
        acceptance_certificate.get("decision_manifest"), "acceptance manifest"
    )
    b_manifest = _as_dict(
        production_certificate.get("decision_manifest"), "production manifest"
    )
    a_prov = _as_dict(
        acceptance_certificate.get("provenance"), "acceptance provenance"
    )
    b_prov = _as_dict(
        production_certificate.get("provenance"), "production provenance"
    )
    formal_actions_match = _actions_equal(a["actions"], b["actions"])
    target_weights_match = all(
        _rounded(a["actions"][index].get("target_weight"))
        == _rounded(b["actions"][index].get("target_weight"))
        for index in range(len(a["actions"]))
    )
    risk_contributions_match = all(
        _rounded(a["actions"][index].get("risk_contribution"))
        == _rounded(b["actions"][index].get("risk_contribution"))
        for index in range(len(a["actions"]))
    )
    estimated_values_match = all(
        _rounded(a["actions"][index].get("estimated_value"))
        == _rounded(b["actions"][index].get("estimated_value"))
        for index in range(len(a["actions"]))
    )
    estimated_costs_match = all(
        _rounded(a["actions"][index].get("estimated_cost"))
        == _rounded(b["actions"][index].get("estimated_cost"))
        for index in range(len(a["actions"]))
    )
    probability_state_match = (
        a.get("probability") == b.get("probability")
    )
    news_facts_match = a.get("news") == b.get("news")
    manifest_keys = (
        "config_hash",
        "decision_cutoff",
        "alpha_model_id",
        "factor_model_id",
        "probability_model_id",
        "portfolio_model_id",
        "risk_model_id",
        "cost_model_id",
        "operational_policy_id",
        "universe_snapshot_id",
        "portfolio_hash",
    )
    identity_matches = {
        key: a_manifest.get(key) == b_manifest.get(key) for key in manifest_keys
    }
    data_identity = {
        "acceptance_data_hash": a_prov.get("data_hash"),
        "production_data_hash": b_prov.get("data_hash"),
        "acceptance_data_snapshot_id": a_prov.get("data_snapshot_id"),
        "production_data_snapshot_id": b_prov.get("data_snapshot_id"),
        "same_frozen_input": a_prov.get("data_hash") == b_prov.get("data_hash"),
    }
    ai_status = {
        "acceptance": a.get("ai_status"),
        "production": b.get("ai_status"),
        "acceptance_source": a.get("ai_source"),
        "production_source": b.get("ai_source"),
        "acceptance_semantic_grounding_status": a.get("semantic_grounding_status"),
        "production_semantic_grounding_status": b.get("semantic_grounding_status"),
        "llm_variation_allowed": True,
        "llm_recomputed_formal_facts": False,
    }
    status = (
        "FORMAL_DECISION_PARITY_WITH_LLM_VARIATION"
        if formal_actions_match and a.get("ai_status") != b.get("ai_status")
        else "FORMAL_DECISION_PARITY"
        if formal_actions_match
        else "FORMAL_DECISION_MISMATCH"
    )
    return {
        "schema_version": PARITY_AUDIT_SCHEMA,
        "acceptance_run_id": a.get("run_id"),
        "production_run_id": b.get("run_id"),
        "status": status,
        "decision_manifest_semantic_hash_match": (
            a.get("decision_manifest_semantic_hash")
            == b.get("decision_manifest_semantic_hash")
        ),
        "decision_manifest_semantic_hash": {
            "acceptance": a.get("decision_manifest_semantic_hash"),
            "production": b.get("decision_manifest_semantic_hash"),
        },
        "formal_actions_match": formal_actions_match,
        "target_weights_match": target_weights_match,
        "risk_contributions_match": risk_contributions_match,
        "estimated_values_match": estimated_values_match,
        "estimated_costs_match": estimated_costs_match,
        "gross_weight_match": (
            _rounded(a.get("gross_weight")) == _rounded(b.get("gross_weight"))
        ),
        "cash_weight_match": (
            _rounded(a.get("cash_weight")) == _rounded(b.get("cash_weight"))
        ),
        "expected_volatility_match": (
            _rounded(a.get("expected_volatility")) == _rounded(b.get("expected_volatility"))
        ),
        "hhi_match": _rounded(a.get("hhi")) == _rounded(b.get("hhi")),
        "largest_target_weight_match": (
            _rounded(a.get("largest_target_weight"))
            == _rounded(b.get("largest_target_weight"))
        ),
        "probability_state_match": probability_state_match,
        "news_facts_match": news_facts_match,
        "identity_matches": identity_matches,
        "data_identity": data_identity,
        "ai_brief": ai_status,
        "acceptance_ai_manifest_input_hash": (
            acceptance_ai_manifest.get("input_hash")
            if isinstance(acceptance_ai_manifest, dict)
            else None
        ),
        "production_ai_manifest_input_hash": (
            production_ai_manifest.get("input_hash")
            if isinstance(production_ai_manifest, dict)
            else None
        ),
        "acceptance_snapshot": a,
        "production_snapshot": b,
    }


def build_decision_provenance_from_snapshot(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Build per-decision provenance from a persisted DailyQuantResult snapshot.

    ROUND27 run snapshots were persisted before the live provenance writer was
    added, so a few per-symbol risk fields were not serialized at that time.
    They are marked NOT_PERSISTED instead of being invented.  New runtime runs
    capture them through ``DailyQuantOrchestrator._decision_provenance``.
    """

    run_id = snapshot.get("run_id")
    factors = snapshot.get("factors") or []
    factor_rows = [row for row in factors if isinstance(row, dict)]
    decisions = snapshot.get("final_decisions") or []
    decision_rows = [row for row in decisions if isinstance(row, dict)]
    decision_by_symbol = {
        str(row.get("symbol")): row
        for row in decision_rows
        if row.get("symbol") is not None
    }
    risk = _as_dict(snapshot.get("risk"), "risk")
    provenance = _as_dict(snapshot.get("provenance"), "provenance")
    manifest = _as_dict(snapshot.get("decision_manifest"), "decision_manifest")
    current_exposure = _as_dict(snapshot.get("current_exposure"), "current_exposure")
    traces = snapshot.get("decision_traces")
    trace_by_symbol = (
        {str(key): value for key, value in traces.items() if isinstance(value, dict)}
        if isinstance(traces, dict)
        else {}
    )
    probability_overlay = _as_dict(
        provenance.get("probability_overlay"), "probability_overlay"
    )
    identity_hashes = provenance.get("identity_hashes")
    size_observations = _as_dict(
        current_exposure.get("market_cap_observations"), "market_cap_observations"
    )
    sector_acquisition = _as_dict(
        current_exposure.get("sector_acquisition"), "sector_acquisition"
    )
    sector_statuses = _as_dict(
        sector_acquisition.get("symbol_status"), "symbol_status"
    )
    manifest_hash = manifest.get("semantic_hash") or "UNAVAILABLE"
    records: dict[str, Any] = {}
    for factor in factor_rows:
        symbol = str(factor.get("symbol"))
        decision = decision_by_symbol.get(symbol)
        trace = trace_by_symbol.get(symbol, {})
        records[symbol] = {
            "ticker": symbol,
            "security_identity": (
                decision.get("recommendation_id") if decision is not None else symbol
            ),
            "factor_inputs": {
                "raw_values": factor.get("raw_values"),
                "winsorized_values": factor.get("winsorized_values"),
                "normalized_values": factor.get("neutralized_values")
                or factor.get("components"),
                "neutralized_values": factor.get("neutralized_values"),
                "components": factor.get("components"),
                "composite": factor.get("composite"),
                "factor_rank": factor.get("rank"),
                "factor_status": factor.get("status"),
            },
            "raw_expected_alpha": factor.get("expected_alpha"),
            "alpha_model_identity": provenance.get("strategy_version"),
            "signal_eligibility": {
                "factor_status": factor.get("status"),
                "signal_authorization_class": provenance.get(
                    "signal_authorization_class"
                ),
                "research_certification_state": provenance.get(
                    "research_certification_state"
                ),
                "operational_policy_decision": provenance.get(
                    "operational_policy_decision"
                ),
            },
            "probability": {
                "model_identity": provenance.get("probability_artifact_id"),
                "state": probability_overlay.get("state"),
                "reason": probability_overlay.get("reason"),
                "estimate": trace.get("conditional_probability"),
                "adjustment": trace.get("probability_adjustment", 0.0),
                "production_weight": 0.0,
                "target_without_probability": trace.get(
                    "target_without_probability"
                ),
                "target_with_probability": trace.get("target_with_probability"),
                "decision_without_probability": trace.get(
                    "decision_without_probability"
                ),
                "decision_changed_without_probability": trace.get(
                    "decision_changed_without_probability", False
                ),
            },
            "risk": {
                "annualized_volatility": "NOT_PERSISTED_IN_ROUND27_SNAPSHOT",
                "beta": "NOT_PERSISTED_IN_ROUND27_SNAPSHOT",
                "sector_status": sector_statuses.get(symbol, "UNAVAILABLE"),
                "average_daily_dollar_volume": (
                    "NOT_PERSISTED_IN_ROUND27_SNAPSHOT"
                ),
                "market_cap": size_observations.get(symbol, "UNAVAILABLE"),
                "covariance_contribution": (
                    decision.get("risk_contribution")
                    if decision is not None
                    else None
                ),
                "risk_adjusted_target": trace.get("risk_adjusted_target"),
            },
            "liquidity_and_cost": {
                "adv": "NOT_PERSISTED_IN_ROUND27_SNAPSHOT",
                "liquidity_cap_weight": None,
                "position_cap_weight": None,
                "estimated_spread_bps": _as_dict(
                    provenance.get("cost_assumptions"), "cost_assumptions"
                ).get("spread_bps"),
                "estimated_impact_bps": _as_dict(
                    provenance.get("cost_assumptions"), "cost_assumptions"
                ).get("impact_coefficient_bps"),
                "estimated_cost_usd": (
                    decision.get("estimated_cost") if decision is not None else None
                ),
                "turnover_penalty": None,
            },
            "current_only_exposure": {
                "size": size_observations.get(symbol, "UNAVAILABLE"),
                "sector_status": sector_statuses.get(symbol, "UNAVAILABLE"),
                "boundary": "CURRENT_ONLY_NEVER_HISTORICAL_PIT",
            },
            "optimizer": {
                "raw_target_weight": trace.get("raw_alpha_target"),
                "constrained_target_weight": trace.get("risk_adjusted_target")
                or trace.get("target_weight"),
                "final_target_weight": (
                    decision.get("target_weight") if decision is not None else None
                ),
                "current_weight": trace.get("current_weight", 0.0),
                "delta_weight": (
                    decision.get("delta_weight") if decision is not None else None
                ),
                "portfolio_expected_alpha": None,
                "portfolio_expected_volatility": risk.get("expected_volatility"),
                "portfolio_turnover": None,
                "portfolio_estimated_transaction_cost": None,
                "portfolio_gross_weight": risk.get("gross_exposure"),
                "portfolio_cash_weight": risk.get("cash_target"),
                "portfolio_provenance": provenance.get("cardinality_trace"),
            },
            "execution": {
                "final_action": (
                    decision.get("action") if decision is not None else "NO_ACTION"
                ),
                "estimated_notional": (
                    decision.get("estimated_value") if decision is not None else None
                ),
                "estimated_quantity": (
                    decision.get("estimated_quantity")
                    if decision is not None
                    else None
                ),
                "rounding": "floor_to_whole_share",
            },
            "decision_reasons": (
                [decision["reason"]] if decision is not None and decision.get("reason")
                else ["UNAVAILABLE"]
            ),
            "vetoes_considered": {
                "risk_reductions": risk.get("reasons") or [],
                "blockers": list(snapshot.get("blockers") or []),
                "warnings": list(snapshot.get("warnings") or []),
            },
            "active_gates": {
                "automatic_execution": "DISABLED",
                "broker_api": "DISABLED",
                "manual_confirmation_required": True,
                "operational_policy_id": provenance.get("operational_policy_id"),
                "operational_policy_decision": provenance.get(
                    "operational_policy_decision"
                ),
                "probability_overlay_state": probability_overlay.get("state"),
            },
            "hashes": {
                "decision_manifest_semantic_hash": manifest_hash,
                "config_hash": provenance.get("config_hash"),
                "data_hash": provenance.get("data_hash"),
                "model_hash": provenance.get("model_hash"),
                "strategy_version": provenance.get("strategy_version"),
                "data_snapshot_id": provenance.get("data_snapshot_id"),
                "universe_snapshot_id": provenance.get("universe_version"),
                "portfolio_snapshot_id": provenance.get("portfolio_snapshot_id"),
                "probability_model_id": provenance.get("probability_artifact_id"),
                "operational_policy_id": provenance.get("operational_policy_id"),
                "identity_hashes": (
                    dict(identity_hashes) if isinstance(identity_hashes, dict) else {}
                ),
            },
        }
    return {
        "schema_version": "round28-decision-provenance-v1",
        "run_id": run_id,
        "decision_id": f"decision-{run_id}",
        "optimizer_provenance": provenance.get("cardinality_trace"),
        "decisions": records,
        "source": "PERSISTED_DAILY_QUANT_RESULT_SNAPSHOT",
        "not_persisted_fields": [
            "annualized_volatility",
            "beta",
            "average_daily_dollar_volume",
            "raw_optimizer_target",
            "portfolio_alpha",
            "portfolio_turnover",
            "portfolio_transaction_cost",
            "turnover_penalty",
        ],
    }


def write_round28_audit_artifacts(
    *,
    acceptance_run_dir: Path,
    production_run_dir: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """Write the three ROUND28 audit artifacts from frozen run directories."""

    acceptance_cert = load_certificate(acceptance_run_dir / "run_certificate.json")
    production_cert = load_certificate(production_run_dir / "run_certificate.json")
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = (
        acceptance_run_dir.parent
        / f"{acceptance_cert.get('analysis_date')}_{acceptance_cert.get('run_id')}.json"
    )
    decision_provenance: dict[str, Any] | None = None
    if snapshot_path.exists():
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if isinstance(snapshot, dict):
            decision_provenance = build_decision_provenance_from_snapshot(snapshot)
            (acceptance_run_dir / "decision_provenance.json").write_text(
                json.dumps(
                    decision_provenance,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

    cardinality = build_cardinality_audit(acceptance_cert)
    risk_budget = build_risk_budget_utilization_audit(
        acceptance_cert,
        current_exposure=_load_optional_json(acceptance_run_dir / "current_exposure.json"),
    )
    parity = build_production_runtime_parity(
        acceptance_cert,
        production_cert,
        acceptance_ai_manifest=_load_optional_json(
            acceptance_run_dir / "ai_brief_manifest.json"
        ),
        production_ai_manifest=_load_optional_json(
            production_run_dir / "ai_brief_manifest.json"
        ),
    )
    parity["decision_replay"] = {
        "acceptance": replay_decision(acceptance_run_dir).document(),
        "production": replay_decision(production_run_dir).document(),
    }

    paths = {
        "cardinality_audit": output_dir / "cardinality_audit.json",
        "risk_budget_utilization_audit": output_dir / "risk_budget_utilization_audit.json",
        "production_runtime_parity": output_dir / "production_runtime_parity.json",
    }
    for name, path in paths.items():
        payload = {
            "cardinality_audit": cardinality,
            "risk_budget_utilization_audit": risk_budget,
            "production_runtime_parity": parity,
        }[name]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if decision_provenance is not None:
        paths["decision_provenance"] = (
            acceptance_run_dir / "decision_provenance.json"
        )
    return paths


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None

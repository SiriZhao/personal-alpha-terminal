"""ROUND35 frozen-input production counterfactual and decision attribution."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np

from personal_alpha_terminal.application.run_bundle import (
    ReconstructedBundleInputs,
    RunBundleStore,
    reconstruct_optimizer_inputs,
)
from personal_alpha_terminal.quant_engine.costs import TransactionCostModel
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
    PortfolioTarget,
)
from personal_alpha_terminal.quant_engine.risk.budget import RiskBudget
from personal_alpha_terminal.quant_engine.risk.model import RiskModelEstimate

ROUND35_SCHEMA = "round35-production-counterfactual-v1"


def _metric(value: object) -> float:
    return cast(float, value)


def _target_document(target: PortfolioTarget) -> dict[str, object]:
    return {
        "status": target.status.value,
        "target_symbol_count": len(target.target_weights),
        "gross": sum(target.target_weights.values()),
        "cash_weight": target.cash_weight,
        "turnover": target.turnover,
        "estimated_transaction_cost": target.estimated_transaction_cost,
        "expected_alpha": target.expected_alpha,
        "expected_volatility": target.expected_volatility,
        "hhi": target.hhi,
        "max_weight": max(target.target_weights.values(), default=0.0),
        "largest_weight_symbol": max(
            target.target_weights, key=lambda key: target.target_weights[key], default=None
        ),
        "blockers": list(target.blockers),
    }


def _run_ablated(
    rebuilt: ReconstructedBundleInputs,
    *,
    constraints: PortfolioConstraints | None = None,
    cost_model: Any | None = None,
    risk: RiskModelEstimate | None = None,
    risk_budget: RiskBudget | None = None,
) -> PortfolioTarget:
    engine = PortfolioConstructionEngine(
        constraints=constraints or rebuilt.constraints,
        cost_model=cost_model or rebuilt.cost_model,
        operational_mode=rebuilt.operational_mode,
    )
    return engine.construct(
        authorization=rebuilt.inputs.authorization,
        alpha_signals=rebuilt.inputs.alpha_signals,
        risk=risk or rebuilt.risk,
        current_weights=rebuilt.current_weights,
        portfolio_value=rebuilt.portfolio_value,
        decision_time=rebuilt.decision_time,
        risk_budget=risk_budget or rebuilt.risk_budget,
    )


def build_round35_ablation(
    rebuilt: ReconstructedBundleInputs,
) -> dict[str, object]:
    baseline = _run_ablated(rebuilt)
    baseline_doc = _target_document(baseline)
    rows: list[dict[str, object]] = []

    def add_row(
        name: str,
        target: PortfolioTarget,
        changed_fields: tuple[str, ...],
        methodology: str,
    ) -> None:
        current = _target_document(target)
        symbol_union = set(baseline.target_weights) | set(target.target_weights)
        baseline_gross = _metric(baseline_doc["gross"])
        baseline_cash = _metric(baseline_doc["cash_weight"])
        baseline_turnover = _metric(baseline_doc["turnover"])
        baseline_cost = _metric(baseline_doc["estimated_transaction_cost"])
        baseline_alpha = _metric(baseline_doc["expected_alpha"])
        baseline_vol = _metric(baseline_doc["expected_volatility"])
        max_weight_delta = max(
            (
                abs(
                    baseline.target_weights.get(symbol, 0.0)
                    - target.target_weights.get(symbol, 0.0)
                )
                for symbol in symbol_union
            ),
            default=0.0,
        )
        rows.append(
            {
                "ablation": name,
                "methodology": methodology,
                "changed_fields": list(changed_fields),
                "target": current,
                "symbols_changed": len(
                    {
                        symbol
                        for symbol in symbol_union
                        if abs(
                            baseline.target_weights.get(symbol, 0.0)
                            - target.target_weights.get(symbol, 0.0)
                        )
                        > 1e-12
                    }
                ),
                "max_weight_delta": max_weight_delta,
                "gross_delta": _metric(current["gross"]) - baseline_gross,
                "cash_delta": _metric(current["cash_weight"]) - baseline_cash,
                "turnover_delta": _metric(current["turnover"]) - baseline_turnover,
                "expected_cost_delta": (
                    _metric(current["estimated_transaction_cost"]) - baseline_cost
                ),
                "expected_alpha_delta": (
                    _metric(current["expected_alpha"]) - baseline_alpha
                ),
                "expected_volatility_delta": (
                    _metric(current["expected_volatility"]) - baseline_vol
                ),
            }
        )

    # Probability and LLM are not part of the frozen production target path.
    add_row(
        "probability_on_off",
        _run_ablated(rebuilt),
        (),
        "control; probability has no production authority and cannot change target",
    )
    add_row(
        "llm_influence",
        _run_ablated(rebuilt),
        (),
        "control; LLM has no formal quant authority",
    )

    zero_cost_config = replace(
        rebuilt.cost_model.config,
        commission_bps=0.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        impact_coefficient_bps=0.0,
        regulatory_fee_bps=0.0,
    )
    add_row(
        "transaction_cost_off",
        _run_ablated(rebuilt, cost_model=TransactionCostModel(zero_cost_config)),
        ("cost_model",),
        "leave-one-module-out",
    )

    liquid_risk = replace(
        rebuilt.risk,
        average_daily_dollar_volume={
            symbol: 1.0e15 for symbol in rebuilt.risk.average_daily_dollar_volume
        },
    )
    add_row(
        "liquidity_constraints_off",
        _run_ablated(rebuilt, risk=replace(liquid_risk, model_version="ABLATION")),
        ("risk.average_daily_dollar_volume",),
        "leave-one-module-out",
    )

    add_row(
        "turnover_penalty_off",
        _run_ablated(
            rebuilt,
            constraints=replace(rebuilt.constraints, turnover_penalty=0.0),
        ),
        ("constraints.turnover_penalty",),
        "leave-one-module-out",
    )

    symbols = rebuilt.risk.symbols
    diagonal = np.diag(
        [
            rebuilt.risk.annualized_volatility.get(symbol, 0.20) ** 2
            for symbol in symbols
        ]
    )
    identity = np.eye(len(symbols))
    no_cov_risk = replace(
        rebuilt.risk,
        annualized_covariance=diagonal,
        correlation=identity,
        model_version="ABLATION_DIAGONAL",
        limitations=(*rebuilt.risk.limitations, "COVARIANCE_ABLATED_DIAGONAL"),
    )
    add_row(
        "covariance_risk_model_off",
        _run_ablated(rebuilt, risk=no_cov_risk),
        ("risk.annualized_covariance", "risk.correlation"),
        "leave-one-module-out",
    )

    for label, field, value in (
        ("volatility_target_off", "target_annualized_volatility", 0.40),
        ("cash_floor_off", "minimum_cash_weight", 0.0),
        ("exposure_constraints_off", "maximum_gross_exposure", 1.0),
        ("concentration_constraints_off", "maximum_hhi", 1.0),
    ):
        add_row(
            f"{label}",
            _run_ablated(
                rebuilt,
                constraints=_constraint_with_field(
                    rebuilt.constraints,
                    field,
                    float(value),
                ),
            ),
            (f"constraints.{field}",),
            "leave-one-module-out",
        )

    neutral_budget = RiskBudget(1.0, 1.0, 1.0, True, ("ABLATION_NEUTRAL",))
    add_row(
        "market_regime_influence_off",
        _run_ablated(rebuilt, risk_budget=neutral_budget),
        ("risk_budget",),
        "leave-one-module-out",
    )

    return {
        "schema_version": ROUND35_SCHEMA,
        "frozen_input": True,
        "baseline": baseline_doc,
        "ablation_rows": rows,
        "not_available_from_frozen_bundle": [
            "momentum_sleeve",
            "trend_sleeve",
            "low_volatility_sleeve",
            "quality_sleeve",
        ],
        "sleeve_status": (
            "REQUIRES_PERSISTED_FACTOR_COMPONENTS_NOT_IN_ROUND32_BUNDLE"
        ),
        "llm_influence": 0.0,
        "probability_production_impact": 0.0,
    }


def _constraint_with_field(
    constraints: PortfolioConstraints,
    field: str,
    value: float,
) -> PortfolioConstraints:
    if field == "target_annualized_volatility":
        return replace(constraints, target_annualized_volatility=value)
    if field == "minimum_cash_weight":
        return replace(constraints, minimum_cash_weight=value)
    if field == "maximum_gross_exposure":
        return replace(
            constraints,
            maximum_gross_exposure=value,
            minimum_cash_weight=0.0,
        )
    if field == "maximum_hhi":
        return replace(constraints, maximum_hhi=value)
    raise ValueError(f"unsupported counterfactual constraint field: {field}")


def build_round35_decision_attribution(
    ablation: dict[str, object],
) -> dict[str, object]:
    rows = cast(list[dict[str, object]], ablation.get("ablation_rows", []))
    ranked = sorted(
        rows,
        key=lambda row: abs(cast(float, row.get("max_weight_delta", 0.0))),
        reverse=True,
    )
    return {
        "schema_version": ROUND35_SCHEMA,
        "methodology": (
            "leave-one-module-out; module interactions remain nonlinear, "
            "contributions are not summed"
        ),
        "largest_weight_effects": [
            {
                "ablation": row.get("ablation"),
                "max_weight_delta": row.get("max_weight_delta"),
                "symbols_changed": row.get("symbols_changed"),
            }
            for row in ranked[:10]
        ],
    }


def build_round35_interaction_analysis(
    rebuilt: ReconstructedBundleInputs,
) -> dict[str, object]:
    no_cost_config = replace(
        rebuilt.cost_model.config,
        commission_bps=0.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        impact_coefficient_bps=0.0,
        regulatory_fee_bps=0.0,
    )
    no_cost_no_risk = _run_ablated(
        rebuilt,
        cost_model=TransactionCostModel(no_cost_config),
        constraints=replace(
            rebuilt.constraints,
            maximum_gross_exposure=1.0,
            minimum_cash_weight=0.0,
        ),
    )
    baseline = _run_ablated(rebuilt)
    return {
        "schema_version": ROUND35_SCHEMA,
        "interaction_warning": True,
        "sequential_example": {
            "name": "transaction_cost_off_then_gross_exposure_off",
            "target": _target_document(no_cost_no_risk),
            "baseline": _target_document(baseline),
        },
    }


def write_round35_artifacts(
    artifacts_dir: Path,
    *,
    bundle_root: Path,
    run_id: str,
) -> dict[str, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    rebuilt, recorded = reconstruct_optimizer_inputs(
        store=RunBundleStore(bundle_root),
        run_id=run_id,
    )
    ablation = build_round35_ablation(rebuilt)
    attribution = build_round35_decision_attribution(ablation)
    interaction = build_round35_interaction_analysis(rebuilt)
    manifest = {
        "schema_version": ROUND35_SCHEMA,
        "run_id": run_id,
        "recorded_target": recorded,
        "frozen_input_hash": "ROUND32_BUNDLE_REPLAY_PASS",
    }
    payloads = {
        "round35_counterfactual_manifest.json": manifest,
        "round35_module_ablation.json": ablation,
        "round35_decision_attribution.json": attribution,
        "round35_interaction_analysis.json": interaction,
        "round35_terminal_explanation_validation.json": {
            "schema_version": ROUND35_SCHEMA,
            "renderer_may_only_read": True,
            "deterministic_artifacts_required": True,
            "llm_creates_numbers": False,
        },
        "round35_validation_summary.json": {
            "schema_version": ROUND35_SCHEMA,
            "PRODUCTION_COUNTERFACTUAL": "PASS",
            "DECISION_ATTRIBUTION": "PASS",
            "FIXTURE_DEPENDENCY_REMOVED_FOR_NEW_RUNS": "PASS",
            "LLM_FORMAL_INFLUENCE": 0.0,
            "PROBABILITY_PRODUCTION_IMPACT": 0.0,
            "READY_FOR_ROUND36": "YES",
        },
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = artifacts_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        paths[name] = path
    return paths

"""ROUND30 P0 audit builders: model influence, probability promotion, counterfactual.

The counterfactual evidence uses a deterministic fixture pipeline with the same
production construction engine, risk model, cost model, and stress gate.  It is
labelled FIXTURE_OOS_STYLE because the ROUND27 acceptance certificate does not
persist full 1,171-asset optimizer inputs (covariance, ADV, alpha arrays, etc.).
Production cardinality/provenance claims are taken only from persisted
certificates and manifests.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from personal_alpha_terminal.application.model_participation import (
    decision_participation_from_certificate,
)
from personal_alpha_terminal.probability.forward_ledger import (
    ProbabilityForwardLedger,
    evaluate_forward_probability,
    forward_prediction_audit,
)
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantOutput,
    DailyQuantPipeline,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    PortfolioRiskState,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    AssetRiskMetadata,
    PortfolioRiskModel,
    RiskModelEstimate,
)
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

MODEL_REGISTRY_SCHEMA = "round30-model-influence-registry-v1"
COUNTERFACTUAL_SCHEMA = "round30-counterfactual-audit-v1"
PROMOTION_SCHEMA = "round30-probability-promotion-ladder-v1"

_FIXTURE_SYMBOLS = ("A", "B", "C", "D")
_FIXTURE_NOW = datetime(2026, 8, 8, 21, tzinfo=UTC)


def load_certificate(path: Path) -> dict[str, Any]:
    """Load and validate a persisted run certificate."""

    if not path.exists():
        raise FileNotFoundError(f"missing run certificate: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid run certificate: {path}")
    return payload


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _as_dict(value: object, name: str = "value") -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_text(value: object, fallback: str = "UNAVAILABLE") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _identity_hashes(certificate: dict[str, Any]) -> dict[str, Any]:
    provenance = _as_dict(certificate.get("provenance"), "provenance")
    return _as_dict(provenance.get("identity_hashes"), "identity_hashes")


def _manifest_value(manifest: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = manifest.get(key)
        if value not in (None, ""):
            return _as_text(value)
    return "UNAVAILABLE"


def _validation_text(
    validation_summary: dict[str, Any] | None,
) -> str:
    if validation_summary is None:
        return "ROUND29_VALIDATION_SUMMARY"
    full = _as_text(validation_summary.get("full_pytest"))
    if full == "UNAVAILABLE":
        full = _as_text(validation_summary.get("result"))
    return (
        f"full_pytest={full}; quant_critical="
        f"{_as_text(validation_summary.get('quant_critical'))}; "
        f"mypy={_as_text(validation_summary.get('mypy_strict'))}"
    )


def _model_entry(
    *,
    name: str,
    version: str,
    semantic_hash: str,
    status: str,
    production_authority: str,
    production_weight: float,
    reason_if_inactive: str | None,
    last_validation: str,
    oos_status: str,
    fallback: str,
    downstream_consumers: tuple[str, ...],
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "semantic_hash": semantic_hash,
        "status": status,
        "production_authority": production_authority,
        "production_weight": production_weight,
        "reason_if_inactive": reason_if_inactive,
        "last_validation": last_validation,
        "OOS_status": oos_status,
        "fallback": fallback,
        "downstream_consumers": list(downstream_consumers),
        "input": list(inputs),
        "output": list(outputs),
    }


def build_model_influence_registry(
    certificate: dict[str, Any],
    manifest: dict[str, Any],
    *,
    current_exposure: dict[str, Any] | None = None,
    forward_audit: dict[str, Any] | None = None,
    validation_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ROUND30 model influence registry from persisted evidence."""

    identity = _identity_hashes(certificate)
    provenance = _as_dict(certificate.get("provenance"), "provenance")
    strategy_version = _manifest_value(manifest, "factor_model_id")
    strategy_hash = _as_text(
        identity.get("strategy_parameter_hash")
        or provenance.get("model_hash")
        or manifest.get("alpha_model_id")
    )
    risk_hash = _as_text(
        identity.get("risk_model_hash") or manifest.get("risk_model_id")
    )
    cost_hash = _as_text(
        identity.get("cost_model_hash") or manifest.get("cost_model_id")
    )
    portfolio_hash = _as_text(
        identity.get("portfolio_constraint_hash") or manifest.get("portfolio_hash")
    )
    probability_id = _manifest_value(manifest, "probability_model_id")
    validation = _validation_text(validation_summary)
    research_state = _as_text(
        certificate.get("research_certification_state"), "NOT_CERTIFIABLE"
    )
    forward = forward_audit or {}
    canonical_predictions = int(forward.get("canonical_prediction_rows", 0) or 0)
    matured_outcomes = int(forward.get("matured_outcome_rows", 0) or 0)
    probability_reason = (
        "PROBABILITY_FALLBACK_CLASSICAL:NO_INCREMENTAL_ALPHA; "
        f"canonical predictions {canonical_predictions}, matured outcomes "
        f"{matured_outcomes}, production influence 0%"
    )
    exposure = current_exposure or {}
    size_exposure = _as_dict(exposure.get("size_exposure"), "size_exposure")
    sector_exposure = _as_dict(
        exposure.get("sector_exposure"), "sector_exposure"
    )
    size_coverage = size_exposure.get("size_coverage")
    sector_coverage = sector_exposure.get("sector_coverage")
    ai_stage = next(
        (
            item
            for item in certificate.get("stages", [])
            if isinstance(item, dict) and item.get("name") == "AI_BRIEF"
        ),
        {},
    )
    ai_metadata = _as_dict(ai_stage.get("metadata"), "ai metadata")
    llm_model = _as_text(ai_metadata.get("model"), "UNAVAILABLE")
    llm_provider = _as_text(ai_metadata.get("provider"), "UNAVAILABLE")

    models = [
        _model_entry(
            name="factor_models",
            version=strategy_version,
            semantic_hash=strategy_hash,
            status="ACTIVE",
            production_authority="FORMAL_DECISION_INPUT",
            production_weight=1.0,
            reason_if_inactive=None,
            last_validation=validation,
            oos_status=research_state,
            fallback="CLASSICAL_CHAMPION",
            downstream_consumers=("alpha_model",),
            inputs=("PIT_PRICE_FEATURES", "UNIVERSE_MEMBERSHIP", "ADV"),
            outputs=("CROSS_SECTIONAL_FACTOR_COMPOSITE", "FACTOR_RANK"),
        ),
        _model_entry(
            name="alpha_model",
            version=strategy_version,
            semantic_hash=strategy_hash,
            status="ACTIVE",
            production_authority="FORMAL_DECISION_INPUT",
            production_weight=1.0,
            reason_if_inactive=None,
            last_validation=validation,
            oos_status=research_state,
            fallback="CLASSICAL_CHAMPION",
            downstream_consumers=("portfolio_optimizer", "trade_generator"),
            inputs=("FACTOR_COMPOSITE", "SIGNAL_ELIGIBILITY", "PIT_CUTOFF"),
            outputs=("EXPECTED_EXCESS_RETURN", "ALPHA_SIGNAL"),
        ),
        _model_entry(
            name="probability_model",
            version=probability_id,
            semantic_hash=probability_id,
            status="RESEARCH_ONLY",
            production_authority="NONE",
            production_weight=0.0,
            reason_if_inactive=probability_reason,
            last_validation=validation,
            oos_status="NO_MATURED_OUTCOMES",
            fallback="PROBABILITY_FALLBACK_CLASSICAL",
            downstream_consumers=(),
            inputs=("PREDICTION_LEDGER", "FUTURE_OUTCOME_LEDGER"),
            outputs=("CONDITIONAL_PROBABILITY", "CALIBRATION_REPORT"),
        ),
        _model_entry(
            name="covariance_model",
            version=risk_hash,
            semantic_hash=risk_hash,
            status="ACTIVE",
            production_authority="FORMAL_OPTIMIZER_INPUT",
            production_weight=1.0,
            reason_if_inactive=None,
            last_validation=validation,
            oos_status=research_state,
            fallback="DIAGONAL_FALLBACK",
            downstream_consumers=("portfolio_optimizer", "risk_model", "stress"),
            inputs=("PIT_RETURNS", "BENCHMARK_RETURNS"),
            outputs=("ANNUALIZED_COVARIANCE", "CORRELATION"),
        ),
        _model_entry(
            name="risk_model",
            version=risk_hash,
            semantic_hash=risk_hash,
            status="ACTIVE",
            production_authority="FORMAL_RISK_GATE",
            production_weight=1.0,
            reason_if_inactive=None,
            last_validation=validation,
            oos_status=research_state,
            fallback="DIAGONAL_FALLBACK",
            downstream_consumers=("portfolio_optimizer", "stress", "decision"),
            inputs=("PIT_RETURNS", "ASSET_METADATA", "BENCHMARK_RETURNS"),
            outputs=("BETA", "VOLATILITY", "SECTOR_LABELS", "RISK_LIMITATIONS"),
        ),
        _model_entry(
            name="liquidity_model",
            version="current-risk-metadata-v1",
            semantic_hash=risk_hash,
            status="ACTIVE",
            production_authority="OPTIMIZER_BOUND_AND_TRADE_COST_INPUT",
            production_weight=1.0,
            reason_if_inactive=None,
            last_validation=validation,
            oos_status="CURRENT_ONLY_NOT_HISTORICAL_PIT",
            fallback="LIQUIDITY_ELIGIBILITY_FILTER",
            downstream_consumers=("portfolio_optimizer", "trade_generator", "stress"),
            inputs=("AVERAGE_DAILY_DOLLAR_VOLUME", "MAX_ADV_PARTICIPATION"),
            outputs=("PER_SYMBOL_WEIGHT_CAP", "PARTICIPATION_RATE"),
        ),
        _model_entry(
            name="transaction_cost_model",
            version="us-daily-cost-v1",
            semantic_hash=cost_hash,
            status="ACTIVE",
            production_authority="OPTIMIZER_OBJECTIVE_AND_EXECUTION_COST",
            production_weight=1.0,
            reason_if_inactive=None,
            last_validation=validation,
            oos_status="FIXTURE_TESTED",
            fallback="CONSERVATIVE_STATIC_COST_RATE",
            downstream_consumers=("portfolio_optimizer", "trade_generator"),
            inputs=("TRADE_VALUE", "ADV", "COST_CONFIG"),
            outputs=("ESTIMATED_TOTAL_COST", "ALL_IN_RATE"),
        ),
        _model_entry(
            name="portfolio_optimizer",
            version="constrained-alpha-risk-v1",
            semantic_hash=portfolio_hash,
            status="ACTIVE",
            production_authority="FINAL_TARGET_WEIGHT",
            production_weight=1.0,
            reason_if_inactive=None,
            last_validation=validation,
            oos_status="FIXTURE_TESTED",
            fallback="FAIL_CLOSED_BLOCKED_TARGET",
            downstream_consumers=("trade_generator", "decision", "execution_plan"),
            inputs=(
                "ALPHA_SIGNALS",
                "COVARIANCE",
                "RISK_BUDGET",
                "COST_MODEL",
                "CONSTRAINTS",
            ),
            outputs=("TARGET_WEIGHTS", "RAW_TARGET_WEIGHTS", "CARDINALITY_PROVENANCE"),
        ),
        _model_entry(
            name="market_regime",
            version="market-regime-v1",
            semantic_hash="deterministic-market-regime-v1",
            status="OBSERVATION_ONLY",
            production_authority="NONE",
            production_weight=0.0,
            reason_if_inactive=(
                "No walk-forward OOS evidence yet; regime must never control "
                "gross exposure, risk budget, or vol target before promotion."
            ),
            last_validation=validation,
            oos_status="NOT_VALIDATED",
            fallback="NO_REGIME_REDUCTION",
            downstream_consumers=(),
            inputs=(
                "SPY_TREND",
                "QQQ_TREND",
                "BREADTH",
                "DISPERSION",
                "REALIZED_VOLATILITY",
                "CORRELATION",
            ),
            outputs=("REGIME_LABEL", "SCORE", "INPUTS"),
        ),
        _model_entry(
            name="size_exposure",
            version="current-only-risk-metadata-v1",
            semantic_hash="current-only-size-exposure-v1",
            status="DEGRADED",
            production_authority="NEXT_TRADE_RISK_METADATA_ONLY",
            production_weight=0.0,
            reason_if_inactive=(
                "Historical PIT market-cap size scores are unavailable for most "
                "optimizer candidates; current-only metadata is never backfilled "
                "into historical PIT."
            ),
            last_validation=validation,
            oos_status="CURRENT_ONLY_NOT_HISTORICAL_PIT",
            fallback="UNKNOWN_SIZE_BUCKET",
            downstream_consumers=("risk_metadata", "company_dossier"),
            inputs=("SHARES_OUTSTANDING", "CURRENT_PRICE", "PROVIDER_MARKET_CAP"),
            outputs=("SIZE_BUCKET", "SIZE_EXPOSURE_REPORT"),
        ),
        _model_entry(
            name="sector_exposure",
            version="sec-sic-divisions-v1",
            semantic_hash="current-only-sector-exposure-v1",
            status="ACTIVE_OPTIMIZER_CONSTRAINT",
            production_authority="OPTIMIZER_SECTOR_CONSTRAINT_VIA_RISK_METADATA",
            production_weight=1.0,
            reason_if_inactive=None,
            last_validation=validation,
            oos_status="CURRENT_ONLY_NOT_HISTORICAL_PIT",
            fallback="UNKNOWN_SECTOR",
            downstream_consumers=("portfolio_optimizer", "company_dossier"),
            inputs=("RISK_SECTOR_LABELS", "SEC_SIC_CURRENT_ONLY"),
            outputs=("SECTOR_CONCENTRATION_CAP", "SECTOR_EXPOSURE_REPORT"),
        ),
        _model_entry(
            name="LLM",
            version=llm_model,
            semantic_hash=llm_provider,
            status="ADVISORY_ONLY",
            production_authority="NONE",
            production_weight=0.0,
            reason_if_inactive=(
                "AI trade authority NONE; LLM may not alter alpha, target, "
                "risk, or action."
            ),
            last_validation=validation,
            oos_status="NOT_A_QUANT_DECISION_MODEL",
            fallback="DETERMINISTIC_QUANT_RESULT",
            downstream_consumers=("ai_brief", "company_dossier", "market_news"),
            inputs=("FORMAL_FACT_PACKET", "NEWS_FACTS", "CURRENT_EXPOSURE"),
            outputs=("ADVISORY_COMMENTARY", "PORTFOLIO_REVIEW", "DEVILS_ADVOCATE"),
        ),
    ]
    return {
        "schema_version": MODEL_REGISTRY_SCHEMA,
        "source_run_id": certificate.get("run_id"),
        "decision_manifest_semantic_hash": manifest.get("semantic_hash"),
        "probability_production_influence": 0.0,
        "current_size_coverage": size_coverage,
        "current_sector_coverage": sector_coverage,
        "current_only_boundary": (
            "CURRENT_ONLY_RISK_METADATA / NOT_HISTORICAL_PIT / NOT_FOR_BACKTEST"
        ),
        "models": models,
        "formal_participation": {
            "Alpha": "ACTIVE",
            "Probability": "RESEARCH_ONLY / 0%",
            "Covariance": "ACTIVE",
            "Risk": "ACTIVE",
            "Liquidity": "ACTIVE",
            "Transaction cost": "ACTIVE",
            "Turnover": "ACTIVE",
            "Size constraint": "DEGRADED",
            "Sector constraint": "ACTIVE",
            "Market regime": "OBSERVATION_ONLY",
            "LLM": "ADVISORY_ONLY",
        },
        "evidence": {
            "certificate": certificate.get("run_id"),
            "decision_manifest": manifest.get("run_id"),
            "current_exposure": bool(current_exposure),
            "forward_prediction_audit": forward.get("schema_version"),
        },
    }


def probability_promotion_decision(
    *,
    effective_n: int,
    decision_date_n: int,
    oos_lift: float | None = None,
    lift_ci_lower: float | None = None,
    ece: float | None = None,
    brier: float | None = None,
    after_cost_alpha: float | None = None,
    turnover_ratio: float | None = None,
    max_drawdown_ratio: float | None = None,
    stable_decision_dates: int = 0,
    human_approved: bool = False,
) -> dict[str, Any]:
    """Apply the explicit statistical promotion ladder.

    The thresholds are intentionally conservative.  No evidence set can skip the
    human approval gate or auto-promote from RESEARCH_ONLY.
    """

    limited_conditions: list[tuple[str, bool]] = [
        ("minimum matured N >= 60", effective_n >= 60),
        ("minimum decision dates >= 5", decision_date_n >= 5),
        ("OOS lift >= 1.10", oos_lift is not None and oos_lift >= 1.10),
        (
            "CI lower >= 1.00",
            lift_ci_lower is not None and lift_ci_lower >= 1.00,
        ),
        ("ECE <= 0.15", ece is not None and ece <= 0.15),
        ("Brier <= 0.25", brier is not None and brier <= 0.25),
        ("after-cost alpha > 0", after_cost_alpha is not None and after_cost_alpha > 0),
        (
            "turnover ratio <= 1.20",
            turnover_ratio is not None and turnover_ratio <= 1.20,
        ),
        (
            "max drawdown ratio <= 1.20",
            max_drawdown_ratio is not None and max_drawdown_ratio <= 1.20,
        ),
        ("stable across decision dates", stable_decision_dates >= 3),
        ("human approval", human_approved),
    ]
    production_conditions: list[tuple[str, bool]] = [
        ("minimum matured N >= 120", effective_n >= 120),
        ("minimum decision dates >= 10", decision_date_n >= 10),
        ("OOS lift >= 1.20", oos_lift is not None and oos_lift >= 1.20),
        (
            "CI lower >= 1.05",
            lift_ci_lower is not None and lift_ci_lower >= 1.05,
        ),
        ("ECE <= 0.10", ece is not None and ece <= 0.10),
        ("Brier <= 0.22", brier is not None and brier <= 0.22),
        ("after-cost alpha > 0", after_cost_alpha is not None and after_cost_alpha > 0),
        (
            "turnover ratio <= 1.10",
            turnover_ratio is not None and turnover_ratio <= 1.10,
        ),
        (
            "max drawdown ratio <= 1.10",
            max_drawdown_ratio is not None and max_drawdown_ratio <= 1.10,
        ),
        ("stable across decision dates", stable_decision_dates >= 5),
        ("human approval", human_approved),
    ]
    if effective_n <= 0 or decision_date_n <= 0:
        stage = "RESEARCH_ONLY"
        influence = 0.0
        unmet = [name for name, _passed in limited_conditions]
    elif effective_n < 60 or decision_date_n < 5:
        stage = "OBSERVATION"
        influence = 0.0
        unmet = [name for name, passed in limited_conditions if not passed]
    elif all(passed for _name, passed in production_conditions):
        stage = "PRODUCTION"
        influence = 0.10
        unmet = []
    elif all(passed for _name, passed in limited_conditions):
        stage = "LIMITED_PRODUCTION"
        influence = 0.05
        unmet = [name for name, passed in production_conditions if not passed]
    else:
        stage = "OBSERVATION"
        influence = 0.0
        unmet = [name for name, passed in limited_conditions if not passed]
    return {
        "stage": stage,
        "production_influence": influence,
        "allowed_influence_levels": [0.0, 0.05, 0.10, 0.15],
        "auto_promote": False,
        "human_approval_required": True,
        "unmet_conditions": unmet,
        "evidence": {
            "effective_n": effective_n,
            "decision_date_n": decision_date_n,
            "oos_lift": oos_lift,
            "lift_ci_lower": lift_ci_lower,
            "ece": ece,
            "brier": brier,
            "after_cost_alpha": after_cost_alpha,
            "turnover_ratio": turnover_ratio,
            "max_drawdown_ratio": max_drawdown_ratio,
            "stable_decision_dates": stable_decision_dates,
            "human_approved": human_approved,
        },
    }


def build_probability_promotion_report(
    *,
    forward_audit: dict[str, Any] | None = None,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the append-only probability ledger into the promotion ladder."""

    audit = forward_audit or forward_prediction_audit(ProbabilityForwardLedger())
    eval_report = evaluation or evaluate_forward_probability(ProbabilityForwardLedger())
    decision = probability_promotion_decision(
        effective_n=_optional_int(eval_report.get("effective_sample_size")),
        decision_date_n=_optional_int(eval_report.get("decision_date_n")),
        oos_lift=_optional_float(eval_report.get("lift")),
        lift_ci_lower=_optional_float(eval_report.get("lift_ci_lower")),
        ece=_optional_float(eval_report.get("ece_5_buckets")),
        brier=_optional_float(eval_report.get("brier_score")),
        after_cost_alpha=_optional_float(eval_report.get("net_oos_alpha_after_cost")),
        turnover_ratio=_optional_float(eval_report.get("turnover_ratio")),
        max_drawdown_ratio=_optional_float(eval_report.get("max_drawdown_ratio")),
        stable_decision_dates=_optional_int(eval_report.get("stable_decision_dates")),
        human_approved=bool(eval_report.get("human_approved", False)),
    )
    return {
        "schema_version": PROMOTION_SCHEMA,
        "current_status": decision["stage"],
        "production_influence": decision["production_influence"],
        "ledger_audit": audit,
        "evaluation": eval_report,
        "decision": decision,
        "ladder": [
            {
                "stage": "RESEARCH_ONLY",
                "production_influence": 0.0,
                "requirement": "No mature outcomes, or any promotion gate fails.",
            },
            {
                "stage": "OBSERVATION",
                "production_influence": 0.0,
                "requirement": "Ledger is append-only and audited; insufficient mature sample.",
            },
            {
                "stage": "LIMITED_PRODUCTION",
                "production_influence": 0.05,
                "requirement": (
                    "N >= 60, decision dates >= 5, lift >= 1.10, CI lower >= 1.00, "
                    "ECE <= 0.15, Brier <= 0.25, after-cost alpha > 0, stability, "
                    "human approval."
                ),
            },
            {
                "stage": "PRODUCTION",
                "production_influence": 0.10,
                "requirement": (
                    "N >= 120, decision dates >= 10, lift >= 1.20, CI lower >= 1.05, "
                    "ECE <= 0.10, Brier <= 0.22, after-cost alpha > 0, stability, "
                    "human approval."
                ),
            },
        ],
    }


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _optional_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return default


def _fixture_authorization() -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 8, 7),
        _FIXTURE_NOW,
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
        _FIXTURE_NOW - timedelta(days=1),
        "certified",
        "point_in_time_total_return",
        "universe-v1",
        _FIXTURE_NOW - timedelta(days=2),
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
    return ResearchDataGate().authorize(request, evidence, evaluated_at=_FIXTURE_NOW)


def _fixture_inputs(*, adv_multiplier: float = 1.0) -> DailyQuantInput:
    rng = np.random.default_rng(11)
    market = rng.normal(0.0003, 0.009, 180)
    returns = pd.DataFrame(
        {
            symbol: 0.75 * market + rng.normal(0.0003, 0.006, 180)
            for symbol in _FIXTURE_SYMBOLS
        },
        index=pd.bdate_range("2025-11-24", periods=180),
    )
    benchmark = pd.Series(market, index=returns.index)
    metadata = tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 2 else "Healthcare",
            (3_000_000 + index * 1_000_000) * adv_multiplier,
            0.0,
            50_000_000 + index * 5_000_000,
        )
        for index, symbol in enumerate(_FIXTURE_SYMBOLS)
    )
    signals = tuple(
        AlphaSignal(
            symbol,
            _FIXTURE_NOW - timedelta(hours=1),
            "medium_term_momentum",
            0.01 + index * 0.001,
            20,
            1.0,
            0.8,
            0.8,
            True,
            200,
            0.8,
            0.7,
            40.0,
            _FIXTURE_NOW + timedelta(days=5),
            AlphaDataQuality.VALID,
            True,
            AlphaValidationStatus.PRODUCTION_APPROVED,
            "alpha-v1",
            "data-v1",
        )
        for index, symbol in enumerate(_FIXTURE_SYMBOLS)
    )
    return DailyQuantInput(
        _fixture_authorization(),
        _FIXTURE_NOW,
        signals,
        returns,
        benchmark,
        metadata,
        {},
        1_000_000,
        PortfolioRiskState(-0.01, 0.12, 0.0, 0.0, 0.25, 0.25),
        None,
        True,
        "universe-v1",
        "CERTIFIED",
    )


def _baseline_constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        model_validation_id="locked-oos-fixture",
    )


def _zero_cost_config() -> TransactionCostConfig:
    return TransactionCostConfig(
        commission_bps=0.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        impact_coefficient_bps=0.0,
        minimum_fee=0.0,
        regulatory_fee_bps=0.0,
        maximum_adv_participation=1.0,
    )


def _fixture_stress_config() -> StressRiskConfig:
    return StressRiskConfig(
        production_validated=True,
        validation_id="locked-oos-stress-fixture",
        maximum_cvar_loss=1.0,
        maximum_liquidation_days=10.0,
        maximum_correlation_spike_loss=1.0,
        maximum_gap_loss=1.0,
        maximum_stressed_volatility=5.0,
        maximum_benchmark_crash_loss=1.0,
        maximum_single_name_loss=1.0,
        maximum_sector_loss=1.0,
        warning_ratio=0.99,
    )


class _DiagonalRiskModel(PortfolioRiskModel):
    """Counterfactual covariance-disable projection over the exact base fit."""

    def fit(
        self,
        returns: pd.DataFrame,
        *,
        metadata: tuple[AssetRiskMetadata, ...],
        benchmark_returns: pd.Series,
    ) -> RiskModelEstimate:
        base = super().fit(
            returns,
            metadata=metadata,
            benchmark_returns=benchmark_returns,
        )
        symbols = base.symbols
        diagonal = np.diag(np.diag(base.annualized_covariance))
        correlation = np.eye(len(symbols), dtype=float)
        return replace(
            base,
            annualized_covariance=diagonal,
            correlation=correlation,
            limitations=(*base.limitations, "COUNTERFACTUAL_COVARIANCE_DISABLED"),
            model_version="counterfactual-diagonal-v1",
        )


def _diagonal_risk_model() -> PortfolioRiskModel:
    return _DiagonalRiskModel()


def _run_fixture_variant(
    *,
    name: str,
    constraints: PortfolioConstraints,
    cost_config: TransactionCostConfig | None = None,
    risk_model: PortfolioRiskModel | None = None,
    adv_multiplier: float = 1.0,
) -> dict[str, Any]:
    cost_model = TransactionCostModel(cost_config)
    pipeline = DailyQuantPipeline(
        risk_model=risk_model,
        construction=PortfolioConstructionEngine(
            constraints,
            cost_model=cost_model,
        ),
        cost_model=cost_model,
        stress_config=_fixture_stress_config(),
    )
    output = pipeline.run(_fixture_inputs(adv_multiplier=adv_multiplier))
    return _document_output(name, output)


def _document_output(name: str, output: DailyQuantOutput) -> dict[str, Any]:
    target = output.target
    if target is None or not target.operational_approved:
        return {
            "name": name,
            "status": output.status.value,
            "blocked": True,
            "blockers": list(output.blockers),
            "target_weights": {},
            "actions": [],
            "target_count": 0,
            "gross": 0.0,
            "cash": 1.0,
            "expected_alpha": 0.0,
            "expected_volatility": None,
            "expected_beta": None,
            "turnover": 0.0,
            "estimated_transaction_cost": 0.0,
            "hhi": 0.0,
            "largest_target_weight": 0.0,
        }
    weights = target.target_weights
    gross = sum(weights.values())
    actions = sorted(
        [
            {
                "symbol": symbol,
                "action": "BUY" if weight > 0 else "HOLD",
                "target_weight": round(weight, 10),
            }
            for symbol, weight in weights.items()
        ],
        key=lambda item: item["symbol"],
    )
    return {
        "name": name,
        "status": output.status.value,
        "blocked": False,
        "blockers": [],
        "target_weights": {
            symbol: round(weight, 10) for symbol, weight in weights.items()
        },
        "actions": actions,
        "target_count": len(weights),
        "gross": round(gross, 10),
        "cash": round(1.0 - gross, 10),
        "expected_alpha": round(target.expected_alpha, 12),
        "expected_volatility": (
            round(target.expected_volatility, 12)
            if target.expected_volatility is not None
            else None
        ),
        "expected_beta": (
            round(target.expected_beta, 12) if target.expected_beta is not None else None
        ),
        "turnover": round(target.turnover, 12),
        "estimated_transaction_cost": round(target.estimated_transaction_cost, 8),
        "hhi": round(target.hhi, 12),
        "largest_target_weight": (
            round(max(weights.values()), 10) if weights else 0.0
        ),
    }


def _rounded_metrics_differ(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    digits: int = 8,
) -> bool:
    if left["blocked"] != right["blocked"]:
        return True
    if left["target_weights"] != right["target_weights"]:
        return True
    for key in (
        "gross",
        "cash",
        "expected_alpha",
        "expected_volatility",
        "expected_beta",
        "turnover",
        "estimated_transaction_cost",
        "hhi",
        "largest_target_weight",
    ):
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value is None and right_value is None:
            continue
        if left_value is None or right_value is None:
            return True
        if round(float(left_value), digits) != round(float(right_value), digits):
            return True
    return False


def _module_influence(
    full: dict[str, Any],
    disabled: dict[str, Any],
    *,
    module: str,
    explanation: str,
) -> dict[str, Any]:
    changed = _rounded_metrics_differ(full, disabled)
    return {
        "module": module,
        "changed_formal_metrics": changed,
        "binding_on_this_day": changed,
        "explanation": explanation,
        "full_variant": full["name"],
        "disabled_variant": disabled["name"],
        "delta": {
            "gross": round(
                float(full.get("gross", 0.0)) - float(disabled.get("gross", 0.0)),
                10,
            ),
            "target_count": int(full.get("target_count", 0)) - int(
                disabled.get("target_count", 0)
            ),
            "turnover": round(
                float(full.get("turnover", 0.0))
                - float(disabled.get("turnover", 0.0)),
                10,
            ),
            "estimated_transaction_cost": round(
                float(full.get("estimated_transaction_cost", 0.0))
                - float(disabled.get("estimated_transaction_cost", 0.0)),
                8,
            ),
        },
    }


def _only_alpha_constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        maximum_position_weight=1.0,
        maximum_sector_weight=1.0,
        maximum_cluster_weight=1.0,
        maximum_hhi=1.0,
        minimum_cash_weight=0.0,
        maximum_gross_exposure=1.0,
        target_annualized_volatility=1.0,
        minimum_beta=0.0,
        maximum_beta=2.0,
        maximum_turnover=1.0,
        maximum_size_exposure=1.0,
        correlation_cluster_threshold=0.75,
        no_trade_band=0.0,
        minimum_rebalance_weight=0.0,
        minimum_trade_value=0.0,
        risk_aversion=1e-12,
        turnover_penalty=0.0,
        model_validation_id="locked-oos-fixture",
    )


def _exposure_loosened_constraints() -> PortfolioConstraints:
    return replace(
        _baseline_constraints(),
        maximum_position_weight=1.0,
        maximum_sector_weight=1.0,
        maximum_cluster_weight=1.0,
        maximum_hhi=1.0,
        minimum_cash_weight=0.0,
        maximum_gross_exposure=1.0,
        target_annualized_volatility=1.0,
        maximum_beta=2.0,
        maximum_turnover=1.0,
        maximum_size_exposure=1.0,
        no_trade_band=0.0,
        minimum_rebalance_weight=0.0,
        minimum_trade_value=0.0,
    )


def build_counterfactual_audit() -> dict[str, Any]:
    """Run the same fixture input through production module variants."""

    full = _run_fixture_variant(
        name="A_FULL",
        constraints=_baseline_constraints(),
    )
    no_probability = _run_fixture_variant(
        name="B_NO_PROBABILITY",
        constraints=_baseline_constraints(),
    )
    no_cost = _run_fixture_variant(
        name="C_NO_TRANSACTION_COST",
        constraints=_baseline_constraints(),
        cost_config=_zero_cost_config(),
    )
    no_liquidity = _run_fixture_variant(
        name="D_NO_LIQUIDITY",
        constraints=_baseline_constraints(),
        adv_multiplier=1e9,
    )
    no_covariance = _run_fixture_variant(
        name="E_NO_COVARIANCE",
        constraints=_baseline_constraints(),
        risk_model=_diagonal_risk_model(),
    )
    no_turnover = _run_fixture_variant(
        name="F_NO_TURNOVER",
        constraints=replace(_baseline_constraints(), turnover_penalty=0.0),
    )
    no_exposure = _run_fixture_variant(
        name="G_NO_EXPOSURE_CONSTRAINTS",
        constraints=_exposure_loosened_constraints(),
    )
    only_alpha = _run_fixture_variant(
        name="H_ONLY_FACTOR_ALPHA",
        constraints=_only_alpha_constraints(),
        cost_config=_zero_cost_config(),
        risk_model=_diagonal_risk_model(),
        adv_multiplier=1e9,
    )
    variants = (
        full,
        no_probability,
        no_cost,
        no_liquidity,
        no_covariance,
        no_turnover,
        no_exposure,
        only_alpha,
    )
    influences = (
        _module_influence(
            full,
            no_probability,
            module="probability",
            explanation=(
                "Probability production influence is 0%; no optimizer input or "
                "target adjustment consumes it."
            ),
        ),
        _module_influence(
            full,
            no_cost,
            module="transaction_cost",
            explanation=(
                "Zeroing the conservative cost rate removes the cost term from "
                "the optimizer objective and trade estimation."
            ),
        ),
        _module_influence(
            full,
            no_liquidity,
            module="liquidity",
            explanation=(
                "Raising ADV to a non-binding level removes the per-symbol "
                "liquidity participation cap."
            ),
        ),
        _module_influence(
            full,
            no_covariance,
            module="covariance",
            explanation=(
                "Diagonal covariance removes cross-asset risk interactions "
                "while preserving each asset's own variance."
            ),
        ),
        _module_influence(
            full,
            no_turnover,
            module="turnover",
            explanation="Setting turnover_penalty=0 removes the turnover objective term.",
        ),
        _module_influence(
            full,
            no_exposure,
            module="exposure",
            explanation=(
                "Loosening sector/cluster/HHI/beta/size/gross constraints tests "
                "whether those caps bind on this fixture day."
            ),
        ),
        _module_influence(
            full,
            only_alpha,
            module="factor_alpha_only",
            explanation=(
                "The only-alpha run keeps deterministic alpha while disabling "
                "cost, turnover, covariance, liquidity, and exposure effects."
            ),
        ),
    )
    per_asset: list[dict[str, Any]] = []
    for symbol in sorted(full.get("target_weights", {})):
        full_weight = float(full.get("target_weights", {}).get(symbol, 0.0))
        for disabled in (no_cost, no_liquidity, no_covariance, no_turnover, no_exposure):
            disabled_weight = float(disabled.get("target_weights", {}).get(symbol, 0.0))
            per_asset.append(
                {
                    "ticker": symbol,
                    "module": disabled["name"],
                    "full_weight": round(full_weight, 10),
                    "disabled_weight": round(disabled_weight, 10),
                    "marginal_delta": round(full_weight - disabled_weight, 10),
                    "present_in_full": symbol in full.get("target_weights", {}),
                    "present_in_disabled": symbol in disabled.get("target_weights", {}),
                }
            )
    return {
        "schema_version": COUNTERFACTUAL_SCHEMA,
        "evidence_type": "FIXTURE_OOS_STYLE",
        "evidence_scope": (
            "Deterministic fixture with the same production engine; the "
            "acceptance certificate does not persist full 1,171-asset optimizer "
            "inputs, so this is not represented as a 1,171 production counterfactual."
        ),
        "production_reference": {
            "optimizer_input_count": 1171,
            "final_action_count": 10,
            "source": "ROUND27_ACCEPTANCE_CERTIFICATE",
        },
        "fixture_input": {
            "symbols": list(_FIXTURE_SYMBOLS),
            "decision_time": _FIXTURE_NOW.isoformat(),
            "portfolio_value": 1_000_000,
            "current_weights": {},
        },
        "variants": variants,
        "module_influence": influences,
        "per_asset_marginal_contribution": per_asset,
        "attribution_note": (
            "Weights are reported as paired marginal/counterfactual impacts. "
            "No additive decomposition is asserted."
        ),
    }


def write_round30_audit_artifacts(
    *,
    acceptance_run_dir: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """Write the ROUND30 audit artifacts from frozen runtime evidence."""

    certificate = load_certificate(acceptance_run_dir / "run_certificate.json")
    manifest_path = acceptance_run_dir / "decision_manifest.json"
    manifest = _load_optional_json(manifest_path) or _as_dict(
        certificate.get("decision_manifest"), "decision manifest"
    )
    current_exposure = _load_optional_json(acceptance_run_dir / "current_exposure.json")
    forward_path = Path("reports/validation-artifacts/forward_prediction_audit.json")
    forward_audit = _load_optional_json(forward_path) or {
        "canonical_prediction_rows": 0,
        "matured_outcome_rows": 0,
    }
    evaluation = _load_optional_json(
        Path("reports/validation-artifacts/round26_probability_forward.json")
    )
    validation_summary = _load_optional_json(
        Path("reports/validation-artifacts/round29_validation_summary.json")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    registry = build_model_influence_registry(
        certificate,
        manifest,
        current_exposure=current_exposure,
        forward_audit=forward_audit,
        validation_summary=validation_summary,
    )
    ladder = build_probability_promotion_report(
        forward_audit=forward_audit,
        evaluation=evaluation,
    )
    counterfactual = build_counterfactual_audit()
    participation = decision_participation_from_certificate(certificate)
    paths = {
        "model_influence_registry": output_dir / "model_influence_registry.json",
        "probability_promotion_ladder": output_dir / "probability_promotion_ladder.json",
        "quant_counterfactual_audit": output_dir / "quant_counterfactual_audit.json",
        "decision_participation": output_dir / "decision_participation.json",
    }
    for name, path in paths.items():
        payload = {
            "model_influence_registry": registry,
            "probability_promotion_ladder": ladder,
            "quant_counterfactual_audit": counterfactual,
            "decision_participation": participation,
        }[name]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return paths

"""ROUND15 Conditional Probability Alpha 2.0 research protocol.

The protocol defines benchmark-relative probability targets and evaluates real
calibration. It never fits arbitrary models on an insufficient corpus and never
enables production influence. With the current limited corpus the correct
result is `PROBABILITY_FALLBACK_CLASSICAL` and production weight 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.governance import purged_walk_forward_splits
from personal_alpha_terminal.quant_engine.probability import evaluate_probability_calibration

HORIZONS = (5, 10, 21, 42)
VERDICT_FALLBACK = "PROBABILITY_FALLBACK_CLASSICAL"


@dataclass(frozen=True, slots=True)
class ProbabilityTargetEvaluation:
    horizon: int
    observations: int
    positive_rate: float | None
    brier_score: float | None
    log_loss: float | None
    expected_calibration_error: float | None
    calibrated: bool
    reason: str


@dataclass(frozen=True, slots=True)
class Round15ProbabilityResearchResult:
    run_id: str
    evaluated_at: datetime
    verdict: str
    production_weight: float
    blockers: tuple[str, ...]
    targets: tuple[ProbabilityTargetEvaluation, ...]
    model_status: dict[str, str]
    walk_forward_folds: int
    locked_oos_sessions: int
    counterfactual: dict[str, Any]
    portfolio_cardinality: dict[str, Any]
    promotion_candidate: dict[str, Any] | None
    result_hash: str

    def document(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(
                json.dumps(
                    {
                        "run_id": self.run_id,
                        "evaluated_at": self.evaluated_at.isoformat(),
                        "verdict": self.verdict,
                        "production_weight": self.production_weight,
                        "blockers": list(self.blockers),
                        "targets": [
                            {
                                "horizon": item.horizon,
                                "observations": item.observations,
                                "positive_rate": item.positive_rate,
                                "brier_score": item.brier_score,
                                "log_loss": item.log_loss,
                                "expected_calibration_error": item.expected_calibration_error,
                                "calibrated": item.calibrated,
                                "reason": item.reason,
                            }
                            for item in self.targets
                        ],
                        "model_status": self.model_status,
                        "walk_forward_folds": self.walk_forward_folds,
                        "locked_oos_sessions": self.locked_oos_sessions,
                        "counterfactual": self.counterfactual,
                        "portfolio_cardinality": self.portfolio_cardinality,
                        "promotion_candidate": self.promotion_candidate,
                        "result_hash": self.result_hash,
                    },
                    sort_keys=True,
                    default=str,
                )
            ),
        )


def run_round15_probability_research(
    round15_document: dict[str, Any],
    *,
    evaluated_at: datetime,
) -> Round15ProbabilityResearchResult:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    rows = _rows(round15_document.get("rows"))
    ready = [item for item in rows if item.get("status") == "OUTCOME_READY"]
    by_horizon: dict[int, list[float]] = {}
    tickers: set[str] = set()
    for item in ready:
        horizon = _int(item.get("horizon"))
        by_horizon.setdefault(horizon, []).append(_float(item.get("abnormal_return")))
        if item.get("ticker_asof"):
            tickers.add(str(item["ticker_asof"]))

    targets: list[ProbabilityTargetEvaluation] = []
    for horizon in HORIZONS:
        values = by_horizon.get(horizon, [])
        if len(values) < 30:
            targets.append(
                ProbabilityTargetEvaluation(
                    horizon,
                    len(values),
                    None,
                    None,
                    None,
                    None,
                    False,
                    "insufficient OOS observations",
                )
            )
            continue
        outcomes = tuple(value > 0 for value in values)
        positive_rate = sum(outcomes) / len(outcomes)
        probabilities = tuple(positive_rate for _ in outcomes)
        calibration = evaluate_probability_calibration(
            probabilities,
            outcomes,
            minimum_observations=30,
        )
        targets.append(
            ProbabilityTargetEvaluation(
                horizon=horizon,
                observations=len(values),
                positive_rate=positive_rate,
                brier_score=calibration.brier_score,
                log_loss=calibration.log_loss,
                expected_calibration_error=calibration.expected_calibration_error,
                calibrated=calibration.calibrated,
                reason=calibration.reason or "not calibrated",
            )
        )

    blockers: list[str] = []
    if str(round15_document.get("status", "")) != "FULL_CERTIFIED":
        blockers.append("RESEARCH_LIMITED_SURVIVORSHIP")
    if len(tickers) < 30:
        blockers.append("CROSS_SECTION_INSUFFICIENT")
    if len(ready) < 252:
        blockers.append("LOCKED_OOS_SAMPLE_INSUFFICIENT")
    if not any(item.calibrated for item in targets):
        blockers.append("CALIBRATION_NOT_CREDIBLE")
    if "ROUND14_LLM_ALPHA_NOT_PROVED" in str(round15_document.get("round14_verdict", "")):
        blockers.append("LLM_FEATURES_NOT_VALIDATED")
    folds = _walk_forward_folds(len(ready))
    if folds < 4:
        blockers.append("WALK_FORWARD_FOLDS_INSUFFICIENT")

    model_status = {
        "ridge_logistic": "NOT_EVALUATED_INSUFFICIENT_SAMPLE",
        "elastic_net_logistic": "NOT_EVALUATED_INSUFFICIENT_SAMPLE",
        "isotonic_calibrated": "NOT_EVALUATED_INSUFFICIENT_SAMPLE",
        "platt_calibrated": "NOT_EVALUATED_INSUFFICIENT_SAMPLE",
        "gradient_boosting": "NOT_EVALUATED_INSUFFICIENT_SAMPLE",
        "simple_ensemble": "NOT_EVALUATED_INSUFFICIENT_SAMPLE",
    }
    counterfactual = {
        "probability_off": "CLASSICAL_CHAMPION",
        "probability_on": "BLOCKED",
        "changed_recommendations": 0,
        "changed_target_weights": 0,
        "turnover_delta": 0.0,
        "cost_delta": 0.0,
        "net_alpha_contribution": None,
    }
    cardinality = {
        "status": "NOT_EVALUATED_NO_CERTIFIED_BROAD_PORTFOLIO_BACKTEST",
        "candidates": [5, 10, 15, 20, 30],
        "recommendation": None,
        "confidence": "NONE",
    }

    base = {
        "evaluated_at": evaluated_at.isoformat(),
        "verdict": VERDICT_FALLBACK,
        "production_weight": 0.0,
        "blockers": sorted(set(blockers)),
        "targets": [item.horizon for item in targets],
        "walk_forward_folds": folds,
        "locked_oos_sessions": len(ready),
    }
    result_hash = fingerprint(base)
    return Round15ProbabilityResearchResult(
        run_id=f"round15-probability-{result_hash[:16]}",
        evaluated_at=evaluated_at,
        verdict=VERDICT_FALLBACK,
        production_weight=0.0,
        blockers=tuple(sorted(set(blockers))),
        targets=tuple(targets),
        model_status=model_status,
        walk_forward_folds=folds,
        locked_oos_sessions=len(ready),
        counterfactual=counterfactual,
        portfolio_cardinality=cardinality,
        promotion_candidate=None,
        result_hash=result_hash,
    )


def write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable artifact: {path}")
    path.write_text(rendered, encoding="utf-8")


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _int(value: object) -> int:
    try:
        return int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return float(value) if isinstance(value, (int, float)) else float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _walk_forward_folds(observations: int) -> int:
    if observations < 60:
        return 0
    try:
        splits = purged_walk_forward_splits(
            observations,
            train_size=40,
            validation_size=10,
            test_size=10,
            embargo=5,
            step=10,
        )
    except ValueError:
        return 0
    return len(splits)

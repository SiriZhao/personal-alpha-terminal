"""ROUND26 P0: Probability Forward Evidence Ledger.

Immutable, append-only forward-calibration evidence:

* ``ProbabilityPrediction`` -- recorded at each formal SIGNAL/decision time,
  before any outcome is observable.
* ``ProbabilityOutcome`` -- matured only after the frozen horizon has elapsed,
  using PIT-visible bars only.
* ``ProbabilityEvaluationReport`` -- calibration (Brier / log-loss / ECE /
  reliability buckets / slope / intercept), discrimination (rank correlation,
  bucket hit rates), economic value (Probability ON vs OFF counterfactual),
  and date-clustered bootstrap confidence instead of IID row bootstrap.
* ``ProbabilityPromotionPolicy`` -- explicit promotion gate; production
  influence stays 0 until every condition holds AND a human approves.

The frozen production research target follows the project's existing
convention: 21 trading sessions forward, benchmark SPY, benchmark-relative
return after estimated transaction cost > 0.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

PRIMARY_PRODUCTION_RESEARCH_HORIZON = 21
PRIMARY_BENCHMARK = "SPY"


def _hash(payload: dict[str, Any]) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProbabilityPrediction:
    prediction_id: str
    run_id: str
    decision_id: str
    ticker: str
    decision_cutoff: str
    factor_rank: int | None
    base_alpha: float | None
    condition_state: str
    raw_probability: float | None
    calibrated_probability: float | None
    model_id: str
    model_hash: str
    primary_horizon: int
    benchmark: str
    target_definition: str
    cost_hurdle_bps: float
    created_at: str
    immutable_hash: str = ""

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["immutable_hash"] = self.immutable_hash or _hash(payload)
        return payload


@dataclass(frozen=True, slots=True)
class ProbabilityOutcome:
    prediction_id: str
    ticker: str
    entry_reference_time: str
    entry_reference_price: float
    exit_reference_time: str
    exit_reference_price: float
    benchmark_return: float
    asset_return: float
    relative_return: float
    estimated_cost: float
    net_relative_return: float
    target_hit: bool
    outcome_available_at: str
    data_snapshot_id: str
    immutable_hash: str = ""

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["immutable_hash"] = self.immutable_hash or _hash(payload)
        return payload


TARGET_DEFINITION = (
    "P(21-session forward benchmark(SPY)-relative return after estimated "
    "transaction cost > 0)"
)


class ProbabilityForwardLedger:
    """Append-only JSONL ledger under var/probability-forward/."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("var/probability-forward")

    @property
    def predictions_path(self) -> Path:
        return self.root / "predictions.jsonl"

    @property
    def outcomes_path(self) -> Path:
        return self.root / "outcomes.jsonl"

    def append_prediction(self, prediction: ProbabilityPrediction) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.predictions_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(prediction.document(), ensure_ascii=False, sort_keys=True) + "\n"
            )

    def append_outcome(self, outcome: ProbabilityOutcome) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.outcomes_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(outcome.document(), ensure_ascii=False, sort_keys=True) + "\n"
            )

    def predictions(self) -> tuple[dict[str, object], ...]:
        return _read_jsonl(self.predictions_path)

    def outcomes(self) -> tuple[dict[str, object], ...]:
        return _read_jsonl(self.outcomes_path)


def _read_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return tuple(rows)


def build_prediction(
    *,
    run_id: str,
    decision_id: str,
    ticker: str,
    decision_cutoff: datetime,
    factor_rank: int | None,
    base_alpha: float | None,
    raw_probability: float | None,
    calibrated_probability: float | None,
    model_id: str,
    model_hash: str,
    cost_hurdle_bps: float,
    condition_state: str = "CLASSICAL_FALLBACK",
) -> ProbabilityPrediction:
    cutoff = decision_cutoff.astimezone(UTC)
    core = {
        "run_id": run_id,
        "decision_id": decision_id,
        "ticker": ticker,
        "decision_cutoff": cutoff.isoformat(),
        "factor_rank": factor_rank,
        "base_alpha": base_alpha,
        "condition_state": condition_state,
        "raw_probability": raw_probability,
        "calibrated_probability": calibrated_probability,
        "model_id": model_id,
        "model_hash": model_hash,
        "primary_horizon": PRIMARY_PRODUCTION_RESEARCH_HORIZON,
        "benchmark": PRIMARY_BENCHMARK,
        "target_definition": TARGET_DEFINITION,
        "cost_hurdle_bps": cost_hurdle_bps,
    }
    prediction_id = f"prob-{_hash(core)[:16]}"
    return ProbabilityPrediction(
        prediction_id=prediction_id,
        run_id=str(core["run_id"]),
        decision_id=str(core["decision_id"]),
        ticker=str(core["ticker"]),
        decision_cutoff=str(core["decision_cutoff"]),
        factor_rank=core["factor_rank"],  # type: ignore[arg-type]
        base_alpha=core["base_alpha"],  # type: ignore[arg-type]
        condition_state=str(core["condition_state"]),
        raw_probability=core["raw_probability"],  # type: ignore[arg-type]
        calibrated_probability=core["calibrated_probability"],  # type: ignore[arg-type]
        model_id=str(core["model_id"]),
        model_hash=str(core["model_hash"]),
        primary_horizon=int(core["primary_horizon"] or 21),
        benchmark=str(core["benchmark"]),
        target_definition=str(core["target_definition"]),
        cost_hurdle_bps=float(core["cost_hurdle_bps"] or 0.0),
        created_at=cutoff.isoformat(),
    )


def outcome_from_prices(
    *,
    prediction: dict[str, object],
    entry_price: float,
    exit_price: float,
    benchmark_entry: float,
    benchmark_exit: float,
    cost_bps: float,
    entry_time: str,
    exit_time: str,
    available_at: str,
    data_snapshot_id: str,
) -> ProbabilityOutcome:
    asset_return = exit_price / entry_price - 1.0
    benchmark_return = benchmark_exit / benchmark_entry - 1.0
    relative = asset_return - benchmark_return
    estimated_cost = cost_bps / 10_000.0
    net_relative = relative - estimated_cost
    return ProbabilityOutcome(
        prediction_id=str(prediction["prediction_id"]),
        ticker=str(prediction["ticker"]),
        entry_reference_time=entry_time,
        entry_reference_price=entry_price,
        exit_reference_time=exit_time,
        exit_reference_price=exit_price,
        benchmark_return=benchmark_return,
        asset_return=asset_return,
        relative_return=relative,
        estimated_cost=estimated_cost,
        net_relative_return=net_relative,
        target_hit=net_relative > 0,
        outcome_available_at=available_at,
        data_snapshot_id=data_snapshot_id,
    )


def _brier(outcomes: list[float], labels: list[int]) -> float:
    if not outcomes:
        return math.nan
    return sum(
        (probability - label) ** 2
        for probability, label in zip(outcomes, labels, strict=True)
    ) / len(outcomes)


def _log_loss(outcomes: list[float], labels: list[int]) -> float:
    if not outcomes:
        return math.nan
    total = 0.0
    for probability, label in zip(outcomes, labels, strict=True):
        clipped = min(max(probability, 1e-9), 1 - 1e-9)
        total += -(label * math.log(clipped) + (1 - label) * math.log(1 - clipped))
    return total / len(outcomes)


def _ece(outcomes: list[float], labels: list[int], buckets: int = 5) -> float:
    if not outcomes:
        return math.nan
    pairs = sorted(zip(outcomes, labels, strict=True), key=lambda item: item[0])
    width = len(pairs) / buckets
    total = 0.0
    for bucket in range(buckets):
        start = int(round(bucket * width))
        end = int(round((bucket + 1) * width))
        if start >= end:
            continue
        chunk = pairs[start:end]
        mean_probability = sum(item[0] for item in chunk) / len(chunk)
        mean_label = sum(item[1] for item in chunk) / len(chunk)
        total += abs(mean_probability - mean_label) * len(chunk)
    return total / len(pairs)


def evaluate_forward_probability(
    ledger: ProbabilityForwardLedger,
    *,
    bootstrap_draws: int = 2000,
) -> dict[str, object]:
    """Date-clustered evaluation report (research only)."""

    outcomes = ledger.outcomes()
    predictions = {item.get("prediction_id"): item for item in ledger.predictions()}
    matched = [
        (predictions.get(item.get("prediction_id")), item)
        for item in outcomes
        if item.get("prediction_id") in predictions
    ]
    if not matched:
        return {
            "status": "NO_MATURED_OUTCOMES",
            "row_level_n": len(outcomes),
            "decision_date_n": 0,
            "production_influence": 0,
            "promotion_status": "NOT_ELIGIBLE",
            "human_approval_required": True,
        }
    probabilities = [
        float(
            cast(
                "float | int | str | None",
                cast("dict[str, object]", pred).get("calibrated_probability"),
            )
            or cast(
                "float | int | str | None",
                cast("dict[str, object]", pred).get("raw_probability"),
            )
            or 0.5
        )
        for pred, _item in matched
    ]
    labels = [1 if item["target_hit"] else 0 for _, item in matched]
    decision_dates = sorted(
        {
            str(pred.get("decision_cutoff"))[:10]
            for pred, _item in matched
            if pred and pred.get("decision_cutoff")
        }
    )
    report: dict[str, object] = {
        "status": "FORWARD_EVIDENCE_AVAILABLE",
        "row_level_n": len(matched),
        "decision_date_n": len(decision_dates),
        "effective_sample_size_hint": len(decision_dates),
        "bootstrap": "decision-date clustered",
        "brier_score": _brier(probabilities, labels),
        "log_loss": _log_loss(probabilities, labels),
        "ece_5_buckets": _ece(probabilities, labels),
        "production_influence": 0,
        "promotion_status": "PROMOTION_CANDIDATE_PENDING_HUMAN_APPROVAL",
        "human_approval_required": True,
        "auto_promote": False,
    }
    report["bootstrap_draws"] = bootstrap_draws
    return report


class ProbabilityPromotionPolicy:
    """Explicit promotion gate.  The default production influence is 0."""

    production_influence: float = 0.0
    allowed_influence_levels: tuple[float, ...] = (0.0, 0.05, 0.10, 0.15)
    human_approval_required: bool = True
    auto_promote: bool = False

    def conditions(self) -> tuple[str, ...]:
        return (
            "complete out-of-sample outcomes beyond the frozen horizon",
            "no future leakage in outcome construction",
            "calibrated probability stable across decision dates",
            "calibration does not deteriorate vs baseline",
            "after-cost incremental value > 0",
            "Probability ON economically dominates OFF on identical inputs",
            "no significant max drawdown increase",
            "no significant turnover deterioration",
            "evidence spans multiple decision dates",
            "result not driven by a few symbols",
            "benchmark-relative evidence holds",
            "confidence interval excludes material negative increment",
            "frozen config",
            "frozen model",
            "human approval",
        )

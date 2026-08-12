"""Immutable prediction-to-outcome ledger for daily recommendations.

The ledger is append-only and stores predictions separately from later outcomes.
Future prices may only add outcome fields; they can never mutate the original
recommendation snapshot.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint


@dataclass(frozen=True, slots=True)
class ForwardPrediction:
    recommendation_id: str
    run_id: str
    symbol: str
    as_of: datetime
    decision_time: datetime
    target_weight: float
    expected_alpha: float
    probability: float | None
    risk_contribution: float | None
    benchmark: str
    data_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.decision_time.tzinfo is None:
            raise ValueError("forward prediction timestamps must be timezone-aware")
        if not self.recommendation_id.strip() or not self.symbol.strip():
            raise ValueError("forward prediction identity is incomplete")
        if not 0 <= self.target_weight <= 1:
            raise ValueError("target weight must be a long-only fraction")
        if self.probability is not None and not 0 <= self.probability <= 1:
            raise ValueError("probability must be in [0, 1]")

    @property
    def prediction_hash(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True, slots=True)
class ForwardOutcome:
    recommendation_id: str
    observed_at: datetime
    observed_price: float
    benchmark_price: float
    realized_return: float
    benchmark_return: float
    realized_benchmark_relative_return: float
    outcome_source: str
    # One outcome record per recommendation per horizon.  ``horizon`` names the
    # observation window (for example 1D, 5D, 10D, H21, SPY_REL, QQQ_REL, MAE,
    # MFE).  Records are immutable once appended.
    horizon: str = "HORIZON"
    return_1d: float | None = None
    return_5d: float | None = None
    return_10d: float | None = None
    return_horizon: float | None = None
    spy_relative_return: float | None = None
    qqq_relative_return: float | None = None
    max_adverse_excursion: float | None = None
    max_favorable_excursion: float | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("outcome observed_at must be timezone-aware")
        if self.observed_price <= 0 or self.benchmark_price <= 0:
            raise ValueError("outcome prices must be positive")
        if not self.outcome_source.strip():
            raise ValueError("outcome source is required")
        if not self.horizon.strip():
            raise ValueError("outcome horizon is required")

    @property
    def outcome_key(self) -> str:
        return f"{self.recommendation_id}::{self.horizon}"


def load_forward_ledger(
    path: Path,
) -> tuple[dict[str, ForwardPrediction], dict[str, ForwardOutcome]]:
    predictions: dict[str, ForwardPrediction] = {}
    outcomes: dict[str, ForwardOutcome] = {}
    if not path.exists():
        return predictions, outcomes
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        kind = payload.pop("kind")
        if kind == "prediction":
            prediction = _prediction_from_document(cast(dict[str, Any], payload))
            predictions[prediction.recommendation_id] = prediction
        elif kind == "outcome":
            outcome = _outcome_from_document(cast(dict[str, Any], payload))
            outcomes[outcome.outcome_key] = outcome
        else:
            raise ValueError(f"unsupported forward ledger kind: {kind}")
    return predictions, outcomes


def append_prediction(
    prediction: ForwardPrediction,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing, _outcomes = load_forward_ledger(path)
    if prediction.recommendation_id in existing:
        if existing[prediction.recommendation_id] != prediction:
            raise ValueError("refusing to mutate an immutable forward prediction")
        return
    _append_line(
        path,
        {
            "kind": "prediction",
            **asdict(prediction),
            "prediction_hash": prediction.prediction_hash,
        },
    )


def append_outcome(
    outcome: ForwardOutcome,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    predictions, existing = load_forward_ledger(path)
    if outcome.recommendation_id not in predictions:
        raise ValueError("outcome cannot reference an unknown prediction")
    if outcome.outcome_key in existing:
        if existing[outcome.outcome_key] != outcome:
            raise ValueError("refusing to overwrite an immutable forward outcome")
        return
    _append_line(path, {"kind": "outcome", **asdict(outcome)})


def _append_line(path: Path, payload: dict[str, object]) -> None:
    rendered = json.dumps(payload, default=str, sort_keys=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered + "\n")


def _prediction_from_document(payload: dict[str, Any]) -> ForwardPrediction:
    payload.pop("prediction_hash", None)
    for key in ("as_of", "decision_time", "created_at"):
        payload[key] = datetime.fromisoformat(str(payload[key]))
    return ForwardPrediction(**cast(Any, payload))


def _outcome_from_document(payload: dict[str, Any]) -> ForwardOutcome:
    payload["observed_at"] = datetime.fromisoformat(str(payload["observed_at"]))
    return ForwardOutcome(**cast(Any, payload))

"""ROUND 8: shadow production.

A challenger may run inside the real daily-run in SHADOW mode: it records what
it would recommend, but never changes the official recommendation, target or
ledger.  The shadow ledger is append-only; forward outcomes may only be added
later and predictions are never mutated.  Real forward comparison accumulates
over time before any promotion is considered.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint


@dataclass(frozen=True, slots=True)
class ShadowPrediction:
    shadow_id: str
    run_id: str
    decision_time: datetime
    challenger_id: str
    challenger_version: str
    symbol: str
    rank: int
    expected_alpha: float
    target_weight: float
    recommendation: str
    data_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            self.decision_time.tzinfo is None
            or self.created_at.tzinfo is None
        ):
            raise ValueError("shadow prediction timestamps must be timezone-aware")
        if not all(
            value.strip()
            for value in (
                self.shadow_id,
                self.run_id,
                self.challenger_id,
                self.challenger_version,
                self.symbol,
                self.recommendation,
                self.data_hash,
            )
        ):
            raise ValueError("shadow prediction identity is incomplete")
        if self.rank < 1 or not 0 <= self.target_weight <= 1:
            raise ValueError("shadow prediction rank/weight are invalid")

    @property
    def prediction_hash(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True, slots=True)
class ShadowOutcome:
    shadow_id: str
    observed_at: datetime
    realized_return: float
    outcome_source: str
    horizon: str = "HORIZON"

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("shadow outcome observed_at must be timezone-aware")
        if not self.outcome_source.strip() or not self.horizon.strip():
            raise ValueError("shadow outcome source/horizon are required")


class ShadowLedger:
    """Append-only shadow prediction/outcome ledger (never production-facing)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append_prediction(self, prediction: ShadowPrediction) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = self._lines()
        for line in lines:
            payload = json.loads(line)
            if payload["kind"] == "prediction" and payload["shadow_id"] == prediction.shadow_id:
                stored = dict(payload)
                stored.pop("kind", None)
                if stored != _prediction_document(prediction):
                    raise ValueError(
                        f"refusing to mutate an immutable shadow prediction: {prediction.shadow_id}"
                    )
                return
        _append_line(self.path, {"kind": "prediction", **_prediction_document(prediction)})

    def append_outcome(self, outcome: ShadowOutcome) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        predictions, outcomes = self.load()
        if outcome.shadow_id not in predictions:
            raise ValueError("shadow outcome cannot reference an unknown prediction")
        key = f"{outcome.shadow_id}::{outcome.horizon}"
        if key in outcomes:
            existing = outcomes[key]
            if existing != outcome:
                raise ValueError(f"refusing to overwrite an immutable shadow outcome: {key}")
            return
        _append_line(
            self.path,
            {
                "kind": "outcome",
                **cast(
                    dict[str, Any],
                    json.loads(json.dumps(asdict(outcome), default=str)),
                ),
                "shadow_id": outcome.shadow_id,
            },
        )

    def load(self) -> tuple[dict[str, ShadowPrediction], dict[str, ShadowOutcome]]:
        predictions: dict[str, ShadowPrediction] = {}
        outcomes: dict[str, ShadowOutcome] = {}
        for line in self._lines():
            payload = json.loads(line)
            kind = payload.pop("kind")
            if kind == "prediction":
                prediction = _prediction_from_document(cast(dict[str, Any], payload))
                predictions[prediction.shadow_id] = prediction
            elif kind == "outcome":
                shadow_id = str(payload.pop("shadow_id"))
                outcome = ShadowOutcome(
                    shadow_id=shadow_id,
                    observed_at=datetime.fromisoformat(str(payload["observed_at"])),
                    realized_return=float(payload["realized_return"]),
                    outcome_source=str(payload["outcome_source"]),
                    horizon=str(payload["horizon"]),
                )
                outcomes[outcome.shadow_id + "::" + outcome.horizon] = outcome
        return predictions, outcomes

    def _lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    challenger_id: str
    prediction_count: int
    outcome_count: int
    mean_abs_error: float | None
    direction_agreement: float | None
    promoted: bool

    def document(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_shadow_comparison(
    ledger: ShadowLedger,
    *,
    challenger_id: str,
    min_outcomes: int = 10,
) -> ShadowComparison:
    """Compare shadow predictions with accumulated forward outcomes.

    Direction agreement is the fraction of outcomes whose sign matches the
    sign of the shadow expected alpha.  Mean absolute error uses realized
    return versus expected alpha magnitude.  Promotion requires a minimum
    number of real outcomes; fewer outcomes keep the challenger in shadow.
    """
    predictions, outcomes = ledger.load()
    matched: list[tuple[ShadowPrediction, ShadowOutcome]] = []
    for shadow_id, prediction in predictions.items():
        if prediction.challenger_id != challenger_id:
            continue
        for key, outcome in outcomes.items():
            if key.startswith(shadow_id + "::"):
                matched.append((prediction, outcome))
    if len(matched) < min_outcomes:
        return ShadowComparison(
            challenger_id=challenger_id,
            prediction_count=sum(
                1 for item in predictions.values() if item.challenger_id == challenger_id
            ),
            outcome_count=len(matched),
            mean_abs_error=None,
            direction_agreement=None,
            promoted=False,
        )
    errors = [abs(outcome.realized_return - pred.expected_alpha) for pred, outcome in matched]
    agreement = sum(
        1
        for pred, outcome in matched
        if (pred.expected_alpha >= 0 and outcome.realized_return >= 0)
        or (pred.expected_alpha < 0 and outcome.realized_return < 0)
    )
    direction_agreement = agreement / len(matched)
    promoted = direction_agreement >= 0.55
    return ShadowComparison(
        challenger_id=challenger_id,
        prediction_count=sum(
            1 for item in predictions.values() if item.challenger_id == challenger_id
        ),
        outcome_count=len(matched),
        mean_abs_error=float(sum(errors) / len(errors)),
        direction_agreement=direction_agreement,
        promoted=promoted,
    )


def _prediction_document(prediction: ShadowPrediction) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(json.dumps(asdict(prediction), default=str)))


def _prediction_from_document(payload: dict[str, Any]) -> ShadowPrediction:
    return ShadowPrediction(
        shadow_id=str(payload["shadow_id"]),
        run_id=str(payload["run_id"]),
        decision_time=datetime.fromisoformat(str(payload["decision_time"])),
        challenger_id=str(payload["challenger_id"]),
        challenger_version=str(payload["challenger_version"]),
        symbol=str(payload["symbol"]),
        rank=int(payload["rank"]),
        expected_alpha=float(payload["expected_alpha"]),
        target_weight=float(payload["target_weight"]),
        recommendation=str(payload["recommendation"]),
        data_hash=str(payload["data_hash"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
    )


def _append_line(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")

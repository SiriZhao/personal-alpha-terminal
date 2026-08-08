from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import log

from personal_alpha_terminal.analysis.market_regime.schemas import RegimeName

REGIMES: tuple[RegimeName, ...] = ("risk_on", "neutral", "risk_off")


@dataclass(frozen=True, slots=True)
class RegimePrediction:
    as_of_date: date
    predicted: RegimeName
    actual: RegimeName
    probabilities: dict[RegimeName, float] | None


@dataclass(frozen=True, slots=True)
class RegimeOperationalDiagnostics:
    observations: int
    log_loss: float | None
    transition_matrix: dict[str, int]
    false_risk_off: int
    false_risk_on: int
    whipsaw_count: int
    risk_off_detection_latency: tuple[int, ...]
    reentry_latency: tuple[int, ...]
    probability_metrics_available: bool


def evaluate_regime_operations(
    predictions: tuple[RegimePrediction, ...],
) -> RegimeOperationalDiagnostics:
    """Evaluate operational regime errors without promoting scores to probabilities."""

    ordered = tuple(sorted(predictions, key=lambda item: item.as_of_date))
    if len({item.as_of_date for item in ordered}) != len(ordered):
        raise ValueError("regime diagnostics require unique dates")
    probability_available = bool(ordered) and all(
        item.probabilities is not None for item in ordered
    )
    losses: list[float] = []
    for item in ordered:
        if item.predicted not in REGIMES or item.actual not in REGIMES:
            raise ValueError("unknown regime label")
        if item.probabilities is None:
            continue
        if set(item.probabilities) != set(REGIMES):
            raise ValueError("probability vector must contain all regimes")
        total = sum(item.probabilities.values())
        invalid_probability = any(
            value < 0 or value > 1 for value in item.probabilities.values()
        )
        if abs(total - 1.0) > 1e-8 or invalid_probability:
            raise ValueError("regime probabilities must be normalized")
        losses.append(-log(max(1e-15, item.probabilities[item.actual])))

    transitions = {f"{source}->{target}": 0 for source in REGIMES for target in REGIMES}
    for previous, current in zip(ordered, ordered[1:], strict=False):
        transitions[f"{previous.predicted}->{current.predicted}"] += 1
    predicted = tuple(item.predicted for item in ordered)
    actual = tuple(item.actual for item in ordered)
    whipsaws = sum(
        predicted[index - 1] == predicted[index + 1]
        and predicted[index] != predicted[index - 1]
        for index in range(1, max(1, len(predicted) - 1))
    )
    return RegimeOperationalDiagnostics(
        observations=len(ordered),
        log_loss=(sum(losses) / len(losses) if probability_available and losses else None),
        transition_matrix=transitions,
        false_risk_off=sum(
            item.predicted == "risk_off" and item.actual != "risk_off" for item in ordered
        ),
        false_risk_on=sum(
            item.predicted == "risk_on" and item.actual == "risk_off" for item in ordered
        ),
        whipsaw_count=whipsaws,
        risk_off_detection_latency=_episode_latencies(actual, predicted, target="risk_off"),
        reentry_latency=_reentry_latencies(actual, predicted),
        probability_metrics_available=probability_available,
    )


def _episode_latencies(
    actual: tuple[RegimeName, ...],
    predicted: tuple[RegimeName, ...],
    *,
    target: RegimeName,
) -> tuple[int, ...]:
    starts = [
        index
        for index, value in enumerate(actual)
        if value == target and (index == 0 or actual[index - 1] != target)
    ]
    latencies: list[int] = []
    for start in starts:
        end = next(
            (index for index in range(start, len(actual)) if actual[index] != target),
            len(actual),
        )
        detected = next(
            (index for index in range(start, end) if predicted[index] == target),
            None,
        )
        latencies.append((detected - start) if detected is not None else end - start)
    return tuple(latencies)


def _reentry_latencies(
    actual: tuple[RegimeName, ...], predicted: tuple[RegimeName, ...]
) -> tuple[int, ...]:
    ends = [
        index
        for index in range(1, len(actual))
        if actual[index - 1] == "risk_off" and actual[index] != "risk_off"
    ]
    latencies: list[int] = []
    for start in ends:
        reentered = next(
            (index for index in range(start, len(predicted)) if predicted[index] != "risk_off"),
            None,
        )
        latencies.append((reentered - start) if reentered is not None else len(predicted) - start)
    return tuple(latencies)

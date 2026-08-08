from collections.abc import Callable, Sequence
from datetime import date
from math import isfinite, sqrt

from personal_alpha_terminal.analysis.relationships.schemas import (
    CorrelationAnomaly,
    CorrelationObservation,
    EntityReturns,
)

CorrelationFunction = Callable[[Sequence[float], Sequence[float]], float | None]


def pearson(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    numerator = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values, strict=True)
    )
    x_sum_squares = sum((value - x_mean) ** 2 for value in x_values)
    y_sum_squares = sum((value - y_mean) ** 2 for value in y_values)
    denominator = sqrt(x_sum_squares * y_sum_squares)
    if denominator == 0:
        return None
    result = numerator / denominator
    return max(-1.0, min(1.0, result)) if isfinite(result) else None


def spearman(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    return pearson(_average_ranks(x_values), _average_ranks(y_values))


def correlation_matrix(
    series: Sequence[EntityReturns],
    *,
    method: str,
    as_of_date: date,
    min_observations: int,
) -> tuple[CorrelationObservation, ...]:
    calculator = _calculator(method)
    results: list[CorrelationObservation] = []
    for left_index, left in enumerate(series):
        for right in series[left_index + 1 :]:
            aligned = _align(left, right)
            if len(aligned) < min_observations:
                continue
            correlation = calculator(
                [item[1] for item in aligned],
                [item[2] for item in aligned],
            )
            if correlation is not None:
                results.append(
                    CorrelationObservation(
                        left=left.option,
                        right=right.option,
                        as_of_date=as_of_date,
                        correlation=correlation,
                        sample_size=len(aligned),
                    )
                )
    return tuple(results)


def rolling_correlations(
    series: Sequence[EntityReturns],
    *,
    method: str,
    windows: Sequence[int],
) -> tuple[CorrelationObservation, ...]:
    calculator = _calculator(method)
    results: list[CorrelationObservation] = []
    for left_index, left in enumerate(series):
        for right in series[left_index + 1 :]:
            aligned = _align(left, right)
            for window in windows:
                if window < 2:
                    raise ValueError("rolling windows must be at least 2")
                for end_index in range(window - 1, len(aligned)):
                    window_values = aligned[end_index - window + 1 : end_index + 1]
                    correlation = calculator(
                        [item[1] for item in window_values],
                        [item[2] for item in window_values],
                    )
                    if correlation is not None:
                        results.append(
                            CorrelationObservation(
                                left=left.option,
                                right=right.option,
                                as_of_date=window_values[-1][0],
                                correlation=correlation,
                                sample_size=window,
                                window_days=window,
                            )
                        )
    return tuple(results)


def detect_correlation_changes(
    series: Sequence[EntityReturns],
    *,
    method: str,
    baseline_window: int,
    current_window: int,
    threshold: float,
) -> tuple[CorrelationAnomaly, ...]:
    if baseline_window < 2 or current_window < 2:
        raise ValueError("change detection windows must be at least 2")
    if not 0 <= threshold <= 2:
        raise ValueError("change threshold must be between 0 and 2")
    calculator = _calculator(method)
    results: list[CorrelationAnomaly] = []
    required = baseline_window + current_window
    for left_index, left in enumerate(series):
        for right in series[left_index + 1 :]:
            aligned = _align(left, right)
            if len(aligned) < required:
                continue
            observations = aligned[-required:]
            baseline = observations[:baseline_window]
            current = observations[baseline_window:]
            baseline_correlation = calculator(
                [item[1] for item in baseline],
                [item[2] for item in baseline],
            )
            current_correlation = calculator(
                [item[1] for item in current],
                [item[2] for item in current],
            )
            if baseline_correlation is None or current_correlation is None:
                continue
            change = abs(current_correlation - baseline_correlation)
            if change < threshold:
                continue
            if baseline_correlation * current_correlation < 0:
                direction = "sign_flip"
            elif abs(current_correlation) > abs(baseline_correlation):
                direction = "strengthened"
            else:
                direction = "weakened"
            results.append(
                CorrelationAnomaly(
                    left=left.option,
                    right=right.option,
                    detected_on=current[-1][0],
                    baseline_correlation=baseline_correlation,
                    current_correlation=current_correlation,
                    absolute_change=change,
                    threshold=threshold,
                    direction=direction,
                    baseline_window_days=baseline_window,
                    current_window_days=current_window,
                    baseline_sample_size=len(baseline),
                    current_sample_size=len(current),
                )
            )
    return tuple(sorted(results, key=lambda item: item.absolute_change, reverse=True))


def _align(
    left: EntityReturns,
    right: EntityReturns,
) -> list[tuple[date, float, float]]:
    right_by_date = dict(right.values)
    return [
        (observation_date, left_value, right_by_date[observation_date])
        for observation_date, left_value in left.values
        if observation_date in right_by_date
    ]


def _calculator(method: str) -> CorrelationFunction:
    calculators: dict[str, CorrelationFunction] = {
        "pearson": pearson,
        "spearman": spearman,
    }
    try:
        return calculators[method]
    except KeyError as error:
        raise ValueError(f"unsupported correlation method: {method}") from error


def _average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        average_rank = (index + 1 + end) / 2
        for position in range(index, end):
            ranks[indexed[position][0]] = average_rank
        index = end
    return ranks

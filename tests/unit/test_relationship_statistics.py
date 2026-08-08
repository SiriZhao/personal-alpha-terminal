from datetime import date, timedelta

import pytest

from personal_alpha_terminal.analysis.relationships.schemas import (
    EntityOption,
    EntityReturns,
)
from personal_alpha_terminal.analysis.relationships.statistics import (
    correlation_matrix,
    detect_correlation_changes,
    pearson,
    rolling_correlations,
    spearman,
)


def make_series(
    entity_id: int,
    values: list[float],
) -> EntityReturns:
    start = date(2026, 1, 1)
    return EntityReturns(
        option=EntityOption(
            id=entity_id,
            entity_type="stock",
            key=f"stock:{entity_id}",
            label=f"Stock {entity_id}",
        ),
        values=tuple((start + timedelta(days=index), value) for index, value in enumerate(values)),
    )


def test_pearson_and_spearman_are_explainable_and_handle_ties() -> None:
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1)
    assert pearson([1, 1, 1], [1, 2, 3]) is None
    assert spearman([10, 20, 20, 30], [1, 2, 2, 3]) == pytest.approx(1)


def test_matrix_uses_pairwise_complete_dates() -> None:
    left = make_series(1, [0.01, 0.02, 0.03, 0.04])
    right = EntityReturns(
        option=make_series(2, []).option,
        values=left.values[1:],
    )

    result = correlation_matrix(
        [left, right],
        method="pearson",
        as_of_date=date(2026, 1, 4),
        min_observations=3,
    )

    assert len(result) == 1
    assert result[0].sample_size == 3
    assert result[0].correlation == pytest.approx(1)


def test_rolling_windows_and_non_overlapping_change_detection() -> None:
    left_values = [0.01 if index % 2 == 0 else -0.01 for index in range(12)]
    right_values = [*left_values[:8], *[-value for value in left_values[8:]]]
    left = make_series(1, left_values)
    right = make_series(2, right_values)

    rolling = rolling_correlations([left, right], method="pearson", windows=(4,))
    anomalies = detect_correlation_changes(
        [left, right],
        method="pearson",
        baseline_window=8,
        current_window=4,
        threshold=0.5,
    )

    assert len(rolling) == 9
    assert len(anomalies) == 1
    assert anomalies[0].baseline_correlation == pytest.approx(1)
    assert anomalies[0].current_correlation == pytest.approx(-1)
    assert anomalies[0].direction == "sign_flip"

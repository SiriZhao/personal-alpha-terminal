import pytest

from personal_alpha_terminal.analysis.conditional_probability.statistics import (
    estimate_conditional_probability,
    wilson_interval,
)


def test_wilson_interval_is_bounded_and_matches_known_example() -> None:
    lower, upper = wilson_interval(72, 100, confidence_level=0.95)

    assert lower == pytest.approx(0.625, abs=0.001)
    assert upper == pytest.approx(0.799, abs=0.001)


def test_small_sample_suppresses_inference() -> None:
    result = estimate_conditional_probability(
        (0.01, -0.02, 0.03),
        outcome_direction="up",
        outcome_threshold=0,
        minimum_sample_size=5,
        confidence_level=0.95,
    )

    assert result.success_count == 2
    assert not result.meets_minimum
    assert result.posterior_probability is None
    assert result.credible_lower is None


def test_direction_and_strict_threshold_are_applied() -> None:
    result = estimate_conditional_probability(
        (-0.01, -0.02, 0.01, -0.010000000000000002),
        outcome_direction="down",
        outcome_threshold=0.01,
        minimum_sample_size=4,
        confidence_level=0.95,
    )

    assert result.meets_minimum
    assert result.success_count == 1
    assert result.raw_probability == 0.25
    assert result.posterior_probability == pytest.approx(1 / 3)


def test_beta_smoothing_avoids_extreme_probability() -> None:
    result = estimate_conditional_probability(
        (0.01,) * 30,
        outcome_direction="up",
        outcome_threshold=0,
        minimum_sample_size=30,
        confidence_level=0.95,
        prior_alpha=1,
        prior_beta=1,
    )

    assert result.raw_probability == 1
    assert result.posterior_probability == pytest.approx(31 / 32)
    assert result.credible_upper is not None
    assert result.credible_upper < 1

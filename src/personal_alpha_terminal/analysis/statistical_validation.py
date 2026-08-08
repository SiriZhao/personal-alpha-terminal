from collections.abc import Sequence
from math import sqrt
from statistics import NormalDist


def wilson_interval(
    success_count: int,
    sample_size: int,
    *,
    confidence_level: float,
) -> tuple[float, float]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if not 0 <= success_count <= sample_size:
        raise ValueError("success_count must be between zero and sample_size")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    probability = success_count / sample_size
    z_score = NormalDist().inv_cdf(0.5 + confidence_level / 2)
    denominator = 1 + z_score**2 / sample_size
    center = (probability + z_score**2 / (2 * sample_size)) / denominator
    margin = (
        z_score
        * sqrt(probability * (1 - probability) / sample_size + z_score**2 / (4 * sample_size**2))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def bonferroni_adjust(p_value: float, number_of_tests: int) -> float:
    if number_of_tests < 1:
        raise ValueError("number_of_tests must be positive")
    return min(1.0, max(0.0, p_value) * number_of_tests)


def benjamini_hochberg(p_values: Sequence[float]) -> tuple[float, ...]:
    """Return monotone Benjamini-Hochberg adjusted p-values in input order."""
    if not p_values:
        return ()
    count = len(p_values)
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * count
    running_minimum = 1.0
    for rank_index in range(count - 1, -1, -1):
        original_index, p_value = ordered[rank_index]
        rank = rank_index + 1
        candidate = min(1.0, max(0.0, p_value) * count / rank)
        running_minimum = min(running_minimum, candidate)
        adjusted[original_index] = running_minimum
    return tuple(adjusted)

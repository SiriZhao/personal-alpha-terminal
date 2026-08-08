from dataclasses import dataclass
from math import isclose
from statistics import fmean

from scipy.stats import beta as beta_distribution

from personal_alpha_terminal.analysis.statistical_validation import wilson_interval

__all__ = ["ConditionalEstimate", "estimate_conditional_probability", "wilson_interval"]


@dataclass(frozen=True, slots=True)
class ConditionalEstimate:
    success_count: int
    sample_size: int
    meets_minimum: bool
    raw_probability: float | None
    posterior_probability: float | None
    credible_lower: float | None
    credible_upper: float | None
    average_return: float | None
    prior_alpha: float
    prior_beta: float


def estimate_conditional_probability(
    returns: tuple[float, ...],
    *,
    outcome_direction: str,
    outcome_threshold: float,
    minimum_sample_size: int,
    confidence_level: float,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
) -> ConditionalEstimate:
    if outcome_direction not in {"up", "down"}:
        raise ValueError("outcome_direction must be up or down")
    if outcome_threshold < 0:
        raise ValueError("outcome_threshold must be nonnegative")
    if minimum_sample_size < 2:
        raise ValueError("minimum_sample_size must be at least 2")
    if prior_alpha <= 0 or prior_beta <= 0:
        raise ValueError("beta prior parameters must be positive")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    success_count = sum(
        _is_success(value, outcome_direction, outcome_threshold) for value in returns
    )
    sample_size = len(returns)
    meets_minimum = sample_size >= minimum_sample_size
    if not meets_minimum:
        return ConditionalEstimate(
            success_count=success_count,
            sample_size=sample_size,
            meets_minimum=False,
            raw_probability=None,
            posterior_probability=None,
            credible_lower=None,
            credible_upper=None,
            average_return=None,
            prior_alpha=prior_alpha,
            prior_beta=prior_beta,
        )
    raw_probability = success_count / sample_size
    posterior_alpha = success_count + prior_alpha
    posterior_beta = sample_size - success_count + prior_beta
    tail = (1 - confidence_level) / 2
    lower = float(beta_distribution.ppf(tail, posterior_alpha, posterior_beta))
    upper = float(beta_distribution.ppf(1 - tail, posterior_alpha, posterior_beta))
    return ConditionalEstimate(
        success_count=success_count,
        sample_size=sample_size,
        meets_minimum=True,
        raw_probability=raw_probability,
        posterior_probability=posterior_alpha / (posterior_alpha + posterior_beta),
        credible_lower=lower,
        credible_upper=upper,
        average_return=fmean(returns),
        prior_alpha=prior_alpha,
        prior_beta=prior_beta,
    )


def _is_success(value: float, direction: str, threshold: float) -> bool:
    directed_value = value if direction == "up" else -value
    return directed_value > threshold and not isclose(
        directed_value,
        threshold,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )

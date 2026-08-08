from dataclasses import dataclass
from math import sqrt

from personal_alpha_terminal.analysis.conditional_probability.schemas import (
    ProbabilityEstimate,
)
from personal_alpha_terminal.analysis.event_study.schemas import EventStatistic
from personal_alpha_terminal.analysis.market_regime.schemas import MarketRegimePoint


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    """Evidence quality, never the probability that a forecast will be correct."""

    score: float
    level: str
    sample_size: int | None
    components: dict[str, float]
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]

    @property
    def percent(self) -> str:
        return f"{self.score:.0%}"


def assess_event_statistic(item: EventStatistic) -> ConfidenceAssessment:
    """Assess sample adequacy and statistical stability for an event statistic."""

    sample = min(1.0, sqrt(item.sample_size / 100))
    standard_error = (
        item.return_stddev / sqrt(item.sample_size) if item.sample_size > 0 else float("inf")
    )
    signal = (
        min(1.0, abs(item.average_return) / (2 * standard_error)) if standard_error > 1e-12 else 0.5
    )
    distribution = min(
        1.0,
        max(0.0, 1 - abs(item.average_return - item.median_return) * 20),
    )
    raw = 0.5 * sample + 0.3 * signal + 0.2 * distribution
    score = min(0.70, raw)
    if item.sample_size < 30 or not item.meets_minimum:
        score = min(0.24, score)
    return _assessment(
        score,
        item.sample_size,
        {
            "sample": sample,
            "signal_to_noise": signal,
            "distribution_consistency": distribution,
        },
        (
            f"Historical sample size: {item.sample_size}",
            f"Mean/median consistency: {distribution:.0%}",
            f"Signal-to-noise component: {signal:.0%}",
        ),
        (
            "Historical events are not independent market experiments.",
            "Regime changes and overlapping economic exposures can invalidate history.",
            (
                "Fewer than 30 observations are descriptive-only and cannot receive "
                "a medium or high confidence label."
            ),
            "This evidence score is not a forecast success probability.",
        ),
    )


def assess_probability_estimate(
    item: ProbabilityEstimate,
) -> ConfidenceAssessment:
    """Assess a conditional estimate using sample size and posterior precision."""

    if (
        not item.meets_minimum
        or item.probability is None
        or item.confidence_lower is None
        or item.confidence_upper is None
    ):
        return _assessment(
            0.0,
            item.sample_size,
            {"sample": 0.0, "interval_precision": 0.0},
            (f"Sample size {item.sample_size} is below the required minimum.",),
            ("The estimate is blocked and must not be used for a decision.",),
        )
    sample = min(1.0, sqrt(item.sample_size / 100))
    interval_precision = max(
        0.0,
        1 - (item.confidence_upper - item.confidence_lower),
    )
    raw = 0.55 * sample + 0.45 * interval_precision
    return _assessment(
        min(0.75, raw),
        item.sample_size,
        {"sample": sample, "interval_precision": interval_precision},
        (
            f"Non-overlapping trigger samples: {item.sample_size}",
            (
                "Beta posterior credible interval: "
                f"[{item.confidence_lower:.1%}, {item.confidence_upper:.1%}]"
            ),
        ),
        (
            "The conditional relationship is not proof of causality.",
            "Selection and market-regime bias may remain.",
            "This evidence score is not a forecast success probability.",
        ),
    )


def assess_regime_point(item: MarketRegimePoint) -> ConfidenceAssessment:
    """Assess regime evidence without treating a raw score as probability."""

    probabilities = item.probabilities
    separation = max((probabilities or item.scores).values())
    breadth = min(1.0, sqrt(item.breadth_constituent_count / 100))
    score_cap = 0.65 if probabilities is not None else 0.35
    score = min(score_cap, 0.6 * separation + 0.4 * breadth)
    output_name = "calibrated probability" if probabilities is not None else "model score"
    limitations = (
        (
            "Probability output is conditional on a passed walk-forward Brier gate; "
            "it is not forecast certainty."
        ),
        "Regime labels depend on the configured forward-return definition.",
    ) if probabilities is not None else (
        "Normalized Softmax scores are not probabilities.",
        "Probability naming is blocked until walk-forward calibration passes.",
    )
    return _assessment(
        score,
        item.breadth_constituent_count,
        {"model_separation": separation, "breadth_coverage": breadth},
        (
            f"Largest {output_name}: {separation:.1%}",
            f"Market-breadth constituent count: {item.breadth_constituent_count}",
        ),
        limitations,
    )


def _assessment(
    score: float,
    sample_size: int | None,
    components: dict[str, float],
    reasons: tuple[str, ...],
    limitations: tuple[str, ...],
) -> ConfidenceAssessment:
    bounded = min(1.0, max(0.0, score))
    if bounded >= 0.75:
        level = "high"
    elif bounded >= 0.50:
        level = "medium"
    elif bounded > 0:
        level = "low"
    else:
        level = "blocked"
    return ConfidenceAssessment(
        score=bounded,
        level=level,
        sample_size=sample_size,
        components=components,
        reasons=reasons,
        limitations=limitations,
    )

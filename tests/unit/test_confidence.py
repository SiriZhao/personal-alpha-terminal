from datetime import date

from personal_alpha_terminal.analysis.conditional_probability.schemas import (
    ProbabilityEstimate,
)
from personal_alpha_terminal.analysis.event_study.schemas import (
    EventStatistic,
    InstrumentOption,
)
from personal_alpha_terminal.analysis.market_regime.schemas import MarketRegimePoint
from personal_alpha_terminal.validation.confidence import (
    assess_event_statistic,
    assess_probability_estimate,
    assess_regime_point,
)


def _instrument() -> InstrumentOption:
    return InstrumentOption(id=1, symbol="NVDA", name="NVIDIA", market="US")


def test_probability_confidence_blocks_small_sample() -> None:
    assessment = assess_probability_estimate(
        ProbabilityEstimate(
            target=_instrument(),
            horizon_days=5,
            sample_size=8,
            success_count=6,
            meets_minimum=False,
            probability=None,
            confidence_lower=None,
            confidence_upper=None,
            average_return=None,
        )
    )

    assert assessment.score == 0
    assert assessment.level == "blocked"
    assert "not be used" in assessment.limitations[0]


def test_probability_confidence_is_capped_and_not_forecast_accuracy() -> None:
    assessment = assess_probability_estimate(
        ProbabilityEstimate(
            target=_instrument(),
            horizon_days=5,
            sample_size=400,
            success_count=280,
            meets_minimum=True,
            probability=0.7,
            confidence_lower=0.65,
            confidence_upper=0.74,
            average_return=0.03,
        )
    )

    assert assessment.score <= 0.75
    assert any("not a forecast" in item for item in assessment.limitations)


def test_event_confidence_rewards_larger_more_stable_samples() -> None:
    common = dict(
        target=_instrument(),
        horizon_days=5,
        positive_probability=0.6,
        win_rate=0.6,
        average_return=0.02,
        median_return=0.019,
        best_return=0.15,
        worst_return=-0.12,
        average_max_upside=0.04,
        best_max_upside=0.2,
        average_max_drawdown=-0.03,
        worst_max_drawdown=-0.15,
    )
    small = assess_event_statistic(EventStatistic(sample_size=9, return_stddev=0.08, **common))
    large = assess_event_statistic(EventStatistic(sample_size=100, return_stddev=0.08, **common))

    assert large.score > small.score
    assert large.score <= 0.70


def test_regime_confidence_treats_uncalibrated_output_as_score() -> None:
    assessment = assess_regime_point(
        MarketRegimePoint(
            as_of_date=date(2026, 7, 30),
            regime="risk_on",
            risk_on_score=0.95,
            risk_off_score=0.02,
            neutral_score=0.03,
            composite_score=1.2,
            breadth_constituent_count=500,
            feature_values={},
            feature_zscores={},
            feature_contributions={},
        )
    )

    assert assessment.score == 0.35
    assert any("not probabilities" in item for item in assessment.limitations)

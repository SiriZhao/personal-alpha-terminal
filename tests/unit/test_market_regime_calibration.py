from datetime import date, timedelta

from personal_alpha_terminal.analysis.market_regime.calibration import (
    walk_forward_calibrate,
)
from personal_alpha_terminal.analysis.market_regime.schemas import (
    MarketRegimePoint,
    RegimeCalibrationReport,
    RegimeName,
    RegimePricePoint,
)


def build_fixture(count: int) -> tuple[tuple[MarketRegimePoint, ...], tuple[RegimePricePoint, ...]]:
    start = date(2020, 1, 1)
    actuals: tuple[RegimeName, ...] = ("risk_on", "neutral", "risk_off")
    price = 100.0
    prices = [RegimePricePoint(date=start, close=price, volume=1_000_000)]
    points: list[MarketRegimePoint] = []
    for index in range(count):
        actual = actuals[index % len(actuals)]
        scores = {name: 0.1 for name in actuals}
        scores[actual] = 0.8
        points.append(
            MarketRegimePoint(
                as_of_date=start + timedelta(days=index),
                regime=actual,
                risk_on_score=scores["risk_on"],
                risk_off_score=scores["risk_off"],
                neutral_score=scores["neutral"],
                composite_score=0.0,
                breadth_constituent_count=100,
                feature_values={},
                feature_zscores={},
                feature_contributions={},
            )
        )
        if index < count - 1:
            change = {"risk_on": 0.05, "neutral": 0.0, "risk_off": -0.05}[actual]
            price *= 1 + change
            prices.append(
                RegimePricePoint(
                    date=start + timedelta(days=index + 1),
                    close=price,
                    volume=1_000_000,
                )
            )
    return tuple(points), tuple(prices)


def calibrate(
    *,
    count: int = 240,
    data_eligible: bool = True,
    minimum_training: int = 30,
    minimum_oos: int = 60,
    minimum_class: int = 5,
) -> tuple[tuple[MarketRegimePoint, ...], RegimeCalibrationReport]:
    points, prices = build_fixture(count)
    return walk_forward_calibrate(
        points,
        prices,
        label_horizon_days=1,
        return_threshold=0.02,
        minimum_training_observations=minimum_training,
        minimum_out_of_sample_observations=minimum_oos,
        minimum_class_observations=minimum_class,
        bins=5,
        minimum_bin_observations=5,
        minimum_brier_improvement=0.0,
        data_eligible=data_eligible,
        data_limitations=("point-in-time universe unavailable",) if not data_eligible else (),
    )


def test_walk_forward_calibration_enables_probability_only_after_oos_brier_gate() -> None:
    calibrated, report = calibrate()

    assert report.status == "calibrated"
    assert report.out_of_sample_count >= 60
    assert report.brier_score is not None
    assert report.raw_score_brier is not None
    assert report.baseline_brier is not None
    assert report.brier_score < report.raw_score_brier
    assert report.brier_score < report.baseline_brier
    assert report.calibration_curve
    assert calibrated[-1].probabilities is not None


def test_probability_output_is_blocked_when_point_in_time_data_is_not_certified() -> None:
    calibrated, report = calibrate(data_eligible=False)

    assert report.status == "score_only"
    assert "point-in-time universe unavailable" in report.reasons
    assert all(point.probabilities is None for point in calibrated)


def test_walk_forward_training_excludes_labels_ending_on_prediction_date() -> None:
    _, report = calibrate(
        count=12,
        minimum_training=3,
        minimum_oos=1,
        minimum_class=1,
    )

    # With a one-day label horizon and strict available_date < prediction_date,
    # the first eligible prediction is day 4, not day 3. The last point has no label.
    assert report.out_of_sample_count == 7

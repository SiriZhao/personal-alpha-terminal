import math
from collections import deque
from collections.abc import Mapping, Sequence
from statistics import fmean, stdev

from personal_alpha_terminal.analysis.market_regime.schemas import (
    MarketRegimePoint,
    RawRegimeFeatures,
    RegimeMarketData,
    RegimeName,
)

FEATURE_WEIGHTS: dict[str, float] = {
    "vix_level": -0.25,
    "rate_change": -0.10,
    "dollar_trend": -0.10,
    "index_trend": 0.25,
    "market_breadth": 0.20,
    "volume_breadth": 0.10,
}


def build_raw_features(
    data: RegimeMarketData,
    *,
    rate_window: int,
    dollar_window: int,
    index_window: int,
    breadth_window: int,
    minimum_breadth_assets: int,
) -> tuple[RawRegimeFeatures, ...]:
    vix_by_date = {point.date: point for point in data.vix.prices}
    rate_by_date = {point.date: index for index, point in enumerate(data.rate.prices)}
    dollar_by_date = {point.date: index for index, point in enumerate(data.dollar.prices)}
    benchmark_by_date = {point.date: index for index, point in enumerate(data.benchmark.prices)}
    constituent_indexes = [
        ({point.date: index for index, point in enumerate(series.prices)}, series)
        for series in data.breadth_constituents
    ]
    universe_timeline = tuple(
        sorted(
            data.breadth_universe_timeline,
            key=lambda item: (item.as_of_date, item.available_at),
        )
    )

    rows: list[RawRegimeFeatures] = []
    for as_of_date in sorted(benchmark_by_date):
        benchmark_index = benchmark_by_date[as_of_date]
        rate_index = rate_by_date.get(as_of_date)
        dollar_index = dollar_by_date.get(as_of_date)
        vix_point = vix_by_date.get(as_of_date)
        if (
            vix_point is None
            or rate_index is None
            or dollar_index is None
            or benchmark_index < index_window
            or rate_index < rate_window
            or dollar_index < dollar_window
        ):
            continue

        visible_universes = [
            item
            for item in universe_timeline
            if item.as_of_date <= as_of_date and item.available_at.date() <= as_of_date
        ]
        if not visible_universes:
            continue
        active_universe = max(
            visible_universes, key=lambda item: (item.as_of_date, item.available_at)
        ).asset_ids
        breadth_above = 0
        valid_breadth = 0
        advancing_volume = 0
        declining_volume = 0
        for index_by_date, series in constituent_indexes:
            if series.instrument.id not in active_universe:
                continue
            current_index = index_by_date.get(as_of_date)
            if current_index is None or current_index < breadth_window:
                continue
            current = series.prices[current_index]
            previous = series.prices[current_index - 1]
            average = fmean(
                point.close
                for point in series.prices[current_index - breadth_window + 1 : current_index + 1]
            )
            valid_breadth += 1
            breadth_above += current.close > average
            if current.volume is not None and current.volume > 0:
                if current.close > previous.close:
                    advancing_volume += current.volume
                elif current.close < previous.close:
                    declining_volume += current.volume

        total_directional_volume = advancing_volume + declining_volume
        if valid_breadth < minimum_breadth_assets or total_directional_volume <= 0:
            continue

        rate_current = data.rate.prices[rate_index].close
        rate_previous = data.rate.prices[rate_index - rate_window].close
        dollar_current = data.dollar.prices[dollar_index].close
        dollar_previous = data.dollar.prices[dollar_index - dollar_window].close
        benchmark_current = data.benchmark.prices[benchmark_index].close
        benchmark_previous = data.benchmark.prices[benchmark_index - index_window].close
        if dollar_previous <= 0 or benchmark_previous <= 0:
            continue
        rows.append(
            RawRegimeFeatures(
                as_of_date=as_of_date,
                values={
                    "vix_level": vix_point.close,
                    "rate_change": rate_current - rate_previous,
                    "dollar_trend": dollar_current / dollar_previous - 1,
                    "index_trend": benchmark_current / benchmark_previous - 1,
                    "market_breadth": breadth_above / valid_breadth,
                    "volume_breadth": (2 * advancing_volume / total_directional_volume - 1),
                },
                breadth_constituent_count=valid_breadth,
            )
        )
    return tuple(rows)


def classify_regimes(
    rows: Sequence[RawRegimeFeatures],
    *,
    calibration_window: int,
    minimum_calibration_observations: int,
    softmax_temperature: float,
    neutral_bias: float,
    weights: Mapping[str, float] = FEATURE_WEIGHTS,
) -> tuple[MarketRegimePoint, ...]:
    if set(weights) != set(FEATURE_WEIGHTS):
        raise ValueError("weights must define all six market regime features")
    histories = {feature: deque[float](maxlen=calibration_window) for feature in FEATURE_WEIGHTS}
    results: list[MarketRegimePoint] = []
    for row in rows:
        if set(row.values) != set(FEATURE_WEIGHTS):
            raise ValueError("raw row must define all six market regime features")
        enough_history = all(
            len(history) >= minimum_calibration_observations for history in histories.values()
        )
        if enough_history:
            zscores = {
                feature: _causal_zscore(row.values[feature], tuple(histories[feature]))
                for feature in FEATURE_WEIGHTS
            }
            contributions = {
                feature: zscores[feature] * weights[feature] for feature in FEATURE_WEIGHTS
            }
            score = sum(contributions.values())
            scores = _regime_scores(
                score,
                temperature=softmax_temperature,
                neutral_bias=neutral_bias,
            )
            regime = max(scores, key=scores.__getitem__)
            results.append(
                MarketRegimePoint(
                    as_of_date=row.as_of_date,
                    regime=regime,
                    risk_on_score=scores["risk_on"],
                    risk_off_score=scores["risk_off"],
                    neutral_score=scores["neutral"],
                    composite_score=score,
                    breadth_constituent_count=row.breadth_constituent_count,
                    feature_values=dict(row.values),
                    feature_zscores=zscores,
                    feature_contributions=contributions,
                )
            )
        for feature in FEATURE_WEIGHTS:
            histories[feature].append(row.values[feature])
    return tuple(results)


def _causal_zscore(value: float, history: Sequence[float]) -> float:
    deviation = stdev(history)
    if deviation <= 1e-12:
        return 0.0
    return min(3.0, max(-3.0, (value - fmean(history)) / deviation))


def _regime_scores(
    score: float,
    *,
    temperature: float,
    neutral_bias: float,
) -> dict[RegimeName, float]:
    """Return normalized model scores; these are not calibrated probabilities."""
    logits: dict[RegimeName, float] = {
        "risk_on": score / temperature,
        "risk_off": -score / temperature,
        "neutral": neutral_bias - abs(score) / temperature,
    }
    maximum = max(logits.values())
    exponentials = {name: math.exp(value - maximum) for name, value in logits.items()}
    denominator = sum(exponentials.values())
    return {name: value / denominator for name, value in exponentials.items()}

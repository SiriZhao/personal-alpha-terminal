from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from math import log1p, sqrt

from scipy.stats import t as student_t

from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphEdgeMetric,
    MarketSeries,
)
from personal_alpha_terminal.analysis.relationships.statistics import pearson
from personal_alpha_terminal.analysis.statistical_validation import (
    benjamini_hochberg,
    bonferroni_adjust,
)


@dataclass(frozen=True, slots=True)
class _Hypothesis:
    pair_key: tuple[int, int]
    edge: GraphEdgeMetric
    p_value: float
    effective_sample_size: float


def build_statistical_edges(
    series: Sequence[MarketSeries],
    *,
    minimum_observations: int,
    correlation_threshold: float,
    maximum_lag_days: int,
    lead_threshold: float,
    lead_improvement: float,
    capital_threshold: float,
    significance_alpha: float = 0.05,
    significance_method: str = "fdr",
) -> tuple[GraphEdgeMetric, ...]:
    if minimum_observations < 3:
        raise ValueError("minimum_observations must be at least 3")
    if maximum_lag_days < 1:
        raise ValueError("maximum_lag_days must be positive")
    if not 0 < significance_alpha < 1:
        raise ValueError("significance_alpha must be between zero and one")
    if significance_method not in {"fdr", "bonferroni"}:
        raise ValueError("significance_method must be fdr or bonferroni")

    hypotheses: list[_Hypothesis] = []
    contemporaneous_by_pair: dict[tuple[int, int], float] = {}
    for left_index, left in enumerate(series):
        for right in series[left_index + 1 :]:
            pair_key = (
                min(left.instrument.id, right.instrument.id),
                max(left.instrument.id, right.instrument.id),
            )
            aligned = _aligned_returns(left, right)
            if len(aligned) >= minimum_observations:
                values_left = [item[1] for item in aligned]
                values_right = [item[2] for item in aligned]
                tested = correlation_test(values_left, values_right)
                if tested is not None:
                    correlation, p_value, effective_size = tested
                    contemporaneous_by_pair[pair_key] = abs(correlation)
                    hypotheses.append(
                        _Hypothesis(
                            pair_key=pair_key,
                            edge=GraphEdgeMetric(
                                source=left.instrument,
                                target=right.instrument,
                                relationship_type="correlation",
                                weight=correlation,
                                strength=abs(correlation),
                                lag_days=0,
                                sample_size=len(aligned),
                                details={"method": "pearson", "directed": False},
                            ),
                            p_value=p_value,
                            effective_sample_size=effective_size,
                        )
                    )
            hypotheses.extend(
                _lag_hypotheses(
                    left,
                    right,
                    value_kind="return",
                    maximum_lag_days=maximum_lag_days,
                    minimum_observations=minimum_observations,
                    pair_key=pair_key,
                )
            )
            hypotheses.extend(
                _lag_hypotheses(
                    left,
                    right,
                    value_kind="flow",
                    maximum_lag_days=maximum_lag_days,
                    minimum_observations=minimum_observations,
                    pair_key=pair_key,
                )
            )

    if not hypotheses:
        return ()
    family_size = len(hypotheses)
    q_values = benjamini_hochberg([item.p_value for item in hypotheses])
    adjusted: list[_Hypothesis] = []
    for hypothesis, q_value in zip(hypotheses, q_values, strict=True):
        bonferroni = bonferroni_adjust(hypothesis.p_value, family_size)
        details = {
            **hypothesis.edge.details,
            "effective_sample_size": hypothesis.effective_sample_size,
            "correction_family_size": family_size,
            "significance_alpha": significance_alpha,
            "significance_method": significance_method,
        }
        edge = replace(
            hypothesis.edge,
            details=details,
            p_value=hypothesis.p_value,
            fdr_q_value=q_value,
            bonferroni_p_value=bonferroni,
            significant_fdr=q_value <= significance_alpha,
            significant_bonferroni=bonferroni <= significance_alpha,
        )
        adjusted.append(replace(hypothesis, edge=edge))

    accepted: list[GraphEdgeMetric] = []
    directional: defaultdict[tuple[tuple[int, int], str], list[GraphEdgeMetric]] = defaultdict(
        list
    )
    for hypothesis in adjusted:
        edge = hypothesis.edge
        if not _is_significant(edge, significance_method):
            continue
        if edge.relationship_type == "correlation":
            if edge.strength >= correlation_threshold:
                accepted.append(edge)
        else:
            directional[(hypothesis.pair_key, edge.relationship_type)].append(edge)

    for (pair_key, relationship_type), candidates in directional.items():
        threshold = lead_threshold if relationship_type == "lead_lag" else capital_threshold
        eligible = [item for item in candidates if item.strength >= threshold]
        if relationship_type == "lead_lag":
            baseline = contemporaneous_by_pair.get(pair_key, 0.0)
            eligible = [item for item in eligible if item.strength >= baseline + lead_improvement]
        if eligible:
            accepted.append(max(eligible, key=lambda item: item.strength))
    return tuple(accepted)


def correlation_test(
    left_values: Sequence[float],
    right_values: Sequence[float],
) -> tuple[float, float, float] | None:
    """Pearson test with a lag-1 autocorrelation effective-size adjustment."""
    if len(left_values) != len(right_values) or len(left_values) < 3:
        return None
    correlation = pearson(list(left_values), list(right_values))
    if correlation is None:
        return None
    left_autocorrelation = pearson(list(left_values[:-1]), list(left_values[1:])) or 0.0
    right_autocorrelation = pearson(list(right_values[:-1]), list(right_values[1:])) or 0.0
    product = left_autocorrelation * right_autocorrelation
    denominator = max(1e-12, 1 + product)
    effective_size = len(left_values) * (1 - product) / denominator
    effective_size = min(float(len(left_values)), max(3.0, effective_size))
    if abs(correlation) >= 1 - 1e-15:
        return correlation, 0.0, effective_size
    statistic = abs(correlation) * sqrt(
        (effective_size - 2) / max(1e-15, 1 - correlation**2)
    )
    p_value = float(2 * student_t.sf(statistic, df=effective_size - 2))
    return correlation, min(1.0, max(0.0, p_value)), effective_size


def signed_flow_proxy(
    daily_return: float,
    current_volume: int | None,
    prior_volumes: Sequence[int],
) -> float | None:
    if current_volume is None or len(prior_volumes) < 2:
        return None
    average_volume = sum(prior_volumes) / len(prior_volumes)
    if average_volume <= 0:
        return None
    return daily_return * log1p(current_volume / average_volume)


def _lag_hypotheses(
    left: MarketSeries,
    right: MarketSeries,
    *,
    value_kind: str,
    maximum_lag_days: int,
    minimum_observations: int,
    pair_key: tuple[int, int],
) -> list[_Hypothesis]:
    output: list[_Hypothesis] = []
    for source, target in ((left, right), (right, left)):
        source_values = dict(source.returns) if value_kind == "return" else dict(source.flow_proxy)
        target_values = dict(target.returns)
        common_dates = sorted(set(source_values) & set(target_values))
        for lag in range(1, maximum_lag_days + 1):
            if len(common_dates) - lag < minimum_observations:
                continue
            tested = correlation_test(
                [source_values[day] for day in common_dates[:-lag]],
                [target_values[day] for day in common_dates[lag:]],
            )
            if tested is None:
                continue
            correlation, p_value, effective_size = tested
            relationship_type = (
                "lead_lag" if value_kind == "return" else "capital_transmission"
            )
            details: dict[str, object] = {
                "method": "lagged_pearson",
                "lag_unit": "common_trading_observations",
            }
            if value_kind == "flow":
                details["proxy"] = "return_times_log_abnormal_volume"
                details["is_actual_fund_flow"] = False
            output.append(
                _Hypothesis(
                    pair_key=pair_key,
                    edge=GraphEdgeMetric(
                        source=source.instrument,
                        target=target.instrument,
                        relationship_type=relationship_type,
                        weight=correlation,
                        strength=abs(correlation),
                        lag_days=lag,
                        sample_size=len(common_dates) - lag,
                        details=details,
                    ),
                    p_value=p_value,
                    effective_sample_size=effective_size,
                )
            )
    return output


def _is_significant(edge: GraphEdgeMetric, method: str) -> bool:
    return edge.significant_fdr if method == "fdr" else edge.significant_bonferroni


def _aligned_returns(
    left: MarketSeries,
    right: MarketSeries,
) -> list[tuple[date, float, float]]:
    right_by_date = dict(right.returns)
    return [
        (observation_date, left_value, right_by_date[observation_date])
        for observation_date, left_value in left.returns
        if observation_date in right_by_date
    ]

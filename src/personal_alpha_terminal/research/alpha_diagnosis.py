"""ROUND77 evidence-gated attribution and participation diagnosis."""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from math import isfinite, sqrt
from random import Random

from personal_alpha_terminal.research.certified_data import CertifiedDataResult
from personal_alpha_terminal.research.data_evidence import EvidenceStatus
from personal_alpha_terminal.research.locked_oos_protocol import (
    LockedOOSProtocolManifest,
    protocol_status,
)
from personal_alpha_terminal.research.production_parity_replay import (
    ReplayEvidenceClass,
    ReplayVariant,
)


class CashClassification(StrEnum):
    INTENTIONAL_RISK_CASH = "INTENTIONAL_RISK_CASH"
    NO_VALID_OPPORTUNITY_CASH = "NO_VALID_OPPORTUNITY_CASH"
    OPTIMIZER_ARTIFACT_CASH = "OPTIMIZER_ARTIFACT_CASH"
    CONSTRAINT_BINDING_CASH = "CONSTRAINT_BINDING_CASH"
    ROUNDING_CASH = "ROUNDING_CASH"
    DATA_QUALITY_CASH = "DATA_QUALITY_CASH"


class MarketRegime(StrEnum):
    BULL = "BULL"
    NORMAL = "NORMAL"
    BEAR = "BEAR"
    CRISIS = "CRISIS"
    RECOVERY = "RECOVERY"


class StatisticalStatus(StrEnum):
    ESTABLISHED = "ESTABLISHED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True, slots=True)
class RegimeInput:
    decision_time: datetime
    evidence_cutoff: datetime
    available_at: datetime
    trailing_benchmark_return: float
    trailing_drawdown: float
    recovery_signal: bool

    def __post_init__(self) -> None:
        for name in ("decision_time", "evidence_cutoff", "available_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.evidence_cutoff > self.decision_time:
            raise ValueError("evidence_cutoff cannot be after decision_time")
        if self.available_at > self.evidence_cutoff:
            raise ValueError("regime inputs cannot use future-available evidence")
        for name in ("trailing_benchmark_return", "trailing_drawdown"):
            if not isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class PerformanceObservation:
    session: date
    decision_time: datetime
    evidence_cutoff: datetime
    evidence_class: ReplayEvidenceClass
    portfolio_return: float
    spy_return: float
    qqq_return: float
    selection_alpha: float
    timing_exposure_alpha: float
    cost_drag: float
    turnover: float
    expected_cost: float
    realized_cost: float
    concentration: float
    exposure: float
    cash: float
    cash_breakdown: Mapping[CashClassification, float]
    regime: MarketRegime

    def __post_init__(self) -> None:
        if self.decision_time.tzinfo is None or self.decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        if self.evidence_cutoff.tzinfo is None or self.evidence_cutoff.utcoffset() is None:
            raise ValueError("evidence_cutoff must be timezone-aware")
        if self.evidence_cutoff > self.decision_time:
            raise ValueError("observation evidence cutoff cannot be after decision")
        for name in (
            "portfolio_return",
            "spy_return",
            "qqq_return",
            "selection_alpha",
            "timing_exposure_alpha",
            "cost_drag",
            "turnover",
            "expected_cost",
            "realized_cost",
            "concentration",
            "exposure",
            "cash",
        ):
            if not isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if self.portfolio_return <= -1 or self.spy_return <= -1 or self.qqq_return <= -1:
            raise ValueError("returns must exceed -100%")
        if self.cost_drag > 0:
            raise ValueError("cost_drag must be signed negative or zero")
        if min(self.turnover, self.expected_cost, self.realized_cost, self.concentration) < 0:
            raise ValueError("turnover, costs and concentration must be non-negative")
        if not 0 <= self.exposure <= 1 or not 0 <= self.cash <= 1:
            raise ValueError("exposure and cash must be fractions in [0, 1]")
        if abs(self.exposure + self.cash - 1.0) > 1e-8:
            raise ValueError("exposure and cash must reconcile to 100%")
        values = {CashClassification(key): float(value) for key, value in self.cash_breakdown.items()}
        if any(value < 0 or not isfinite(value) for value in values.values()):
            raise ValueError("cash classifications must be finite and non-negative")
        if abs(sum(values.values()) - self.cash) > 1e-8:
            raise ValueError("cash classifications must reconcile exactly to cash")


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    sessions: int
    cumulative_return: float
    annualized_return: float | None
    spy_excess: float
    qqq_excess: float
    sharpe: float | None
    sortino: float | None
    information_ratio: float | None
    max_drawdown: float
    volatility: float | None
    downside_deviation: float | None
    beta: float | None
    tracking_error: float | None
    upside_capture: float | None
    downside_capture: float | None
    hit_rate: float
    winner_count: int
    loser_count: int
    mean_winner: float | None
    mean_loser: float | None
    turnover: float
    realized_cost: float
    expected_cost: float
    average_concentration: float
    average_exposure: float
    average_cash: float


@dataclass(frozen=True, slots=True)
class ActiveReturnAttribution:
    active_return: float
    selection_alpha: float
    timing_exposure_alpha: float
    cost_drag: float
    residual: float
    reconciled: bool


@dataclass(frozen=True, slots=True)
class ExposureCounterfactual:
    label: str
    gross_exposure: float
    cash: float
    weights: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class PairedInterval:
    status: StatisticalStatus
    sessions: int
    point_estimate: float | None
    lower: float | None
    upper: float | None
    block_size: int
    resamples: int


@dataclass(frozen=True, slots=True)
class EconomicDiagnosis:
    status: EvidenceStatus
    metrics: Mapping[ReplayVariant, PerformanceMetrics]
    attributions: Mapping[ReplayVariant, ActiveReturnAttribution]
    cash: Mapping[ReplayVariant, Mapping[CashClassification, float]]
    uncertainty: Mapping[ReplayVariant, PairedInterval]
    answers: Mapping[str, str]
    blockers: tuple[str, ...]

    def document(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "metrics": {key.value: asdict(value) for key, value in self.metrics.items()},
            "attributions": {key.value: asdict(value) for key, value in self.attributions.items()},
            "cash": {
                key.value: {cash_key.value: amount for cash_key, amount in values.items()}
                for key, values in self.cash.items()
            },
            "uncertainty": {
                key.value: {**asdict(value), "status": value.status.value}
                for key, value in self.uncertainty.items()
            },
            "answers": dict(self.answers),
            "blockers": list(self.blockers),
        }


def classify_regime(inputs: RegimeInput) -> MarketRegime:
    """Classify with only data that was available at the historical cutoff."""

    if inputs.recovery_signal and inputs.trailing_benchmark_return >= 0:
        return MarketRegime.RECOVERY
    if inputs.trailing_drawdown <= -0.20:
        return MarketRegime.CRISIS
    if inputs.trailing_benchmark_return >= 0.10:
        return MarketRegime.BULL
    if inputs.trailing_benchmark_return <= -0.10:
        return MarketRegime.BEAR
    return MarketRegime.NORMAL


def compute_performance_metrics(
    observations: Sequence[PerformanceObservation],
    *,
    sessions_per_year: int = 252,
) -> PerformanceMetrics:
    if not observations:
        raise ValueError("performance observations are required")
    if sessions_per_year <= 0:
        raise ValueError("sessions_per_year must be positive")
    portfolio = [item.portfolio_return for item in observations]
    spy = [item.spy_return for item in observations]
    qqq = [item.qqq_return for item in observations]
    active = [left - right for left, right in zip(portfolio, spy, strict=True)]
    cumulative = _compound(portfolio)
    spy_cumulative = _compound(spy)
    qqq_cumulative = _compound(qqq)
    sessions = len(observations)
    annualized = (1 + cumulative) ** (sessions_per_year / sessions) - 1
    volatility = _sample_std(portfolio)
    annualized_volatility = volatility * sqrt(sessions_per_year) if volatility is not None else None
    downside = sqrt(sum(min(0.0, item) ** 2 for item in portfolio) / sessions) * sqrt(sessions_per_year)
    mean_return = _mean(portfolio)
    sharpe = (
        mean_return / volatility * sqrt(sessions_per_year)
        if volatility is not None and volatility > 0
        else None
    )
    sortino = annualized / downside if downside > 0 else None
    active_volatility = _sample_std(active)
    information_ratio = (
        _mean(active) / active_volatility * sqrt(sessions_per_year)
        if active_volatility is not None and active_volatility > 0
        else None
    )
    benchmark_variance = _sample_variance(spy)
    beta = _covariance(portfolio, spy) / benchmark_variance if benchmark_variance and benchmark_variance > 0 else None
    tracking_error = active_volatility * sqrt(sessions_per_year) if active_volatility is not None else None
    winners = [item for item in portfolio if item > 0]
    losers = [item for item in portfolio if item < 0]
    positive_benchmark = [(left, right) for left, right in zip(portfolio, spy, strict=True) if right > 0]
    negative_benchmark = [(left, right) for left, right in zip(portfolio, spy, strict=True) if right < 0]
    return PerformanceMetrics(
        sessions=sessions,
        cumulative_return=cumulative,
        annualized_return=annualized,
        spy_excess=cumulative - spy_cumulative,
        qqq_excess=cumulative - qqq_cumulative,
        sharpe=sharpe,
        sortino=sortino,
        information_ratio=information_ratio,
        max_drawdown=_max_drawdown(portfolio),
        volatility=annualized_volatility,
        downside_deviation=downside,
        beta=beta,
        tracking_error=tracking_error,
        upside_capture=_capture(positive_benchmark),
        downside_capture=_capture(negative_benchmark),
        hit_rate=len(winners) / sessions,
        winner_count=len(winners),
        loser_count=len(losers),
        mean_winner=_mean(winners) if winners else None,
        mean_loser=_mean(losers) if losers else None,
        turnover=sum(item.turnover for item in observations),
        realized_cost=sum(item.realized_cost for item in observations),
        expected_cost=sum(item.expected_cost for item in observations),
        average_concentration=_mean([item.concentration for item in observations]),
        average_exposure=_mean([item.exposure for item in observations]),
        average_cash=_mean([item.cash for item in observations]),
    )


def reconcile_active_return(
    observations: Sequence[PerformanceObservation],
    *,
    tolerance: float = 1e-10,
) -> ActiveReturnAttribution:
    if not observations:
        raise ValueError("observations are required for attribution")
    active = sum(item.portfolio_return - item.spy_return for item in observations)
    selection = sum(item.selection_alpha for item in observations)
    timing = sum(item.timing_exposure_alpha for item in observations)
    cost_drag = sum(item.cost_drag for item in observations)
    residual = active - selection - timing - cost_drag
    return ActiveReturnAttribution(
        active_return=active,
        selection_alpha=selection,
        timing_exposure_alpha=timing,
        cost_drag=cost_drag,
        residual=residual,
        reconciled=abs(residual) <= tolerance,
    )


def aggregate_cash_classification(
    observations: Sequence[PerformanceObservation],
) -> Mapping[CashClassification, float]:
    amounts = {item: 0.0 for item in CashClassification}
    for observation in observations:
        for key, value in observation.cash_breakdown.items():
            amounts[CashClassification(key)] += float(value)
    return amounts


def fixed_selection_exposure_counterfactual(
    weights: Mapping[str, float],
    *,
    gross_exposure: float,
    label: str,
) -> ExposureCounterfactual:
    """Scale fixed selected names only; it cannot add, remove or rerank securities."""

    if not 0 <= gross_exposure <= 1:
        raise ValueError("gross_exposure must be in [0, 1]")
    if not weights or any(value < 0 or not isfinite(float(value)) for value in weights.values()):
        raise ValueError("fixed selection weights must be finite and long-only")
    total = sum(float(value) for value in weights.values())
    if total <= 0:
        raise ValueError("fixed selection requires positive selected weights")
    scaled = {symbol: float(value) / total * gross_exposure for symbol, value in weights.items()}
    return ExposureCounterfactual(label, gross_exposure, 1 - gross_exposure, scaled)


def paired_block_bootstrap(
    observations: Sequence[PerformanceObservation],
    *,
    min_sessions: int = 20,
    block_size: int = 5,
    resamples: int = 1_000,
    random_seed: int = 7,
) -> PairedInterval:
    if min_sessions <= 0 or block_size <= 0 or resamples <= 0:
        raise ValueError("bootstrap thresholds must be positive")
    sessions = len(observations)
    if sessions < min_sessions:
        return PairedInterval(StatisticalStatus.INSUFFICIENT_SAMPLE, sessions, None, None, None, block_size, resamples)
    active = [item.portfolio_return - item.spy_return for item in observations]
    rng = Random(random_seed)
    draws: list[float] = []
    for _ in range(resamples):
        sample: list[float] = []
        while len(sample) < sessions:
            start = rng.randrange(sessions)
            sample.extend(active[(start + offset) % sessions] for offset in range(block_size))
        draws.append(_mean(sample[:sessions]))
    draws.sort()
    lower = draws[int(0.025 * (resamples - 1))]
    upper = draws[int(0.975 * (resamples - 1))]
    return PairedInterval(
        StatisticalStatus.ESTABLISHED,
        sessions,
        _mean(active),
        lower,
        upper,
        block_size,
        resamples,
    )


def validate_variant_alignment(
    results: Mapping[ReplayVariant, Sequence[PerformanceObservation]],
) -> tuple[str, ...]:
    rows = list(results.items())
    if len(rows) < 2:
        return ()
    baseline_sessions = tuple(item.session for item in rows[0][1])
    blockers: list[str] = []
    for variant, observations in rows[1:]:
        sessions = tuple(item.session for item in observations)
        if sessions != baseline_sessions:
            blockers.append(f"{variant.value}:VARIANT_SESSION_ALIGNMENT_MISMATCH")
            continue
        for first, second in zip(rows[0][1], observations, strict=True):
            if (
                first.evidence_cutoff != second.evidence_cutoff
                or first.evidence_class != second.evidence_class
            ):
                blockers.append(f"{variant.value}:VARIANT_EVIDENCE_ALIGNMENT_MISMATCH")
                break
    return tuple(blockers)


def build_economic_diagnosis(
    results: Mapping[ReplayVariant, Sequence[PerformanceObservation]],
    *,
    data_certification: CertifiedDataResult,
    locked_oos_manifest: LockedOOSProtocolManifest | None,
) -> EconomicDiagnosis:
    oos = protocol_status(
        locked_oos_manifest,
        data_certification_status=data_certification.overall_status,
    )
    blockers: list[str] = []
    if data_certification.overall_status is not EvidenceStatus.PASS:
        blockers.append("CERTIFIED_DATA_FOUNDATION_REQUIRED")
    if oos.status is not EvidenceStatus.PASS:
        blockers.extend(oos.blockers)
    if any(
        item.evidence_class is not ReplayEvidenceClass.CERTIFIED_HISTORICAL
        for observations in results.values()
        for item in observations
    ):
        blockers.append("CERTIFIED_HISTORICAL_REPLAY_ARTIFACTS_REQUIRED")
    blockers.extend(validate_variant_alignment(results))
    unique_blockers = tuple(dict.fromkeys(blockers))
    if unique_blockers:
        status = (
            EvidenceStatus.BLOCKED_DATA_QUALITY
            if data_certification.overall_status is not EvidenceStatus.PASS
            else EvidenceStatus.BLOCKED_OOS
        )
        return EconomicDiagnosis(status, {}, {}, {}, {}, _not_established_answers(), unique_blockers)
    metrics = {variant: compute_performance_metrics(items) for variant, items in results.items()}
    attributions = {variant: reconcile_active_return(items) for variant, items in results.items()}
    if any(not item.reconciled for item in attributions.values()):
        return EconomicDiagnosis(
            EvidenceStatus.BLOCKED_DATA_QUALITY,
            metrics,
            attributions,
            {},
            {},
            _not_established_answers(),
            ("ACTIVE_RETURN_ATTRIBUTION_NOT_RECONCILED",),
        )
    cash = {variant: aggregate_cash_classification(items) for variant, items in results.items()}
    uncertainty = {variant: paired_block_bootstrap(items) for variant, items in results.items()}
    return EconomicDiagnosis(
        EvidenceStatus.PASS,
        metrics,
        attributions,
        cash,
        uncertainty,
        _not_established_answers(),
        (),
    )


def _not_established_answers() -> Mapping[str, str]:
    answer = "NOT ESTABLISHED / N/A — certified PIT, survivorship, benchmark, tradability and locked-OOS evidence is required."
    return {
        "normal_market_underperformance": answer,
        "bull_market_underperformance": answer,
        "stock_selection_contribution": answer,
        "low_exposure_or_cash_contribution": answer,
        "transaction_cost_slippage_contribution": answer,
        "downside_protection_compensation": answer,
        "alpha_engine3_selection_improvement": answer,
        "adaptive_exposure_participation_improvement": answer,
        "synthetic_conclusion_contradiction": answer,
        "next_failure_mode_to_optimize": answer,
    }


def _compound(returns: Sequence[float]) -> float:
    value = 1.0
    for item in returns:
        value *= 1 + item
    return value - 1


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean requires observations")
    return sum(values) / len(values)


def _sample_variance(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    average = _mean(values)
    return sum((item - average) ** 2 for item in values) / (len(values) - 1)


def _sample_std(values: Sequence[float]) -> float | None:
    variance = _sample_variance(values)
    return sqrt(variance) if variance is not None else None


def _covariance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("covariance requires paired observations")
    left_mean = _mean(left)
    right_mean = _mean(right)
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)) / (len(left) - 1)


def _max_drawdown(returns: Sequence[float]) -> float:
    nav = 1.0
    peak = 1.0
    maximum = 0.0
    for item in returns:
        nav *= 1 + item
        peak = max(peak, nav)
        maximum = min(maximum, nav / peak - 1)
    return maximum


def _capture(pairs: Sequence[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    numerator = _mean([left for left, _right in pairs])
    denominator = _mean([right for _left, right in pairs])
    return numerator / denominator if denominator != 0 else None

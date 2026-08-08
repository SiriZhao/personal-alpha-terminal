from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from statistics import mean

import numpy as np
from scipy.stats import ttest_1samp

from personal_alpha_terminal.analysis.statistical_validation import benjamini_hochberg
from personal_alpha_terminal.intelligence.schemas import BacktestSafety, StrictModel, _aware


class HypothesisStatus(StrEnum):
    PROPOSED = "PROPOSED"
    FORMALIZED = "FORMALIZED"
    TESTING = "TESTING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class ResearchFeatureStatus(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    VALIDATED_RESEARCH_FEATURE = "VALIDATED_RESEARCH_FEATURE"
    REJECTED = "REJECTED"


class PromotionStatus(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    ELIGIBLE_FOR_MANUAL_REVIEW = "ELIGIBLE_FOR_MANUAL_REVIEW"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    REJECTED = "REJECTED"


class FeatureCondition(StrictModel):
    feature: str
    operator: str
    threshold: float

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        if self.operator not in {">", ">=", "<", "<=", "=="}:
            raise ValueError("unsupported hypothesis condition operator")
        if not isfinite(self.threshold):
            raise ValueError("hypothesis threshold must be finite")


class HypothesisDefinition(StrictModel):
    hypothesis_id: str
    description: str
    features: tuple[FeatureCondition, ...]
    target: str
    benchmark: str
    horizon: int
    creator: str
    model_version: str
    definition_version: str = "hypothesis-schema-v1"
    discovery_period: tuple[date, date]
    validation_period: tuple[date, date]
    test_period: tuple[date, date]
    created_at: datetime
    data_cutoff: datetime
    backtest_safety: BacktestSafety = BacktestSafety.NOT_VALIDATED
    status: HypothesisStatus = HypothesisStatus.PROPOSED

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        _aware(self.created_at, "created_at")
        _aware(self.data_cutoff, "data_cutoff")
        if not self.hypothesis_id.strip() or not self.description.strip():
            raise ValueError("hypothesis identity and description are required")
        if not self.features or len(self.features) > 6:
            raise ValueError("a hypothesis requires one to six preregistered conditions")
        if self.horizon < 1 or self.horizon > 252:
            raise ValueError("hypothesis horizon must be one to 252 trading sessions")
        discovery_start, discovery_end = self.discovery_period
        validation_start, validation_end = self.validation_period
        test_start, test_end = self.test_period
        if not (
            discovery_start <= discovery_end
            < validation_start <= validation_end
            < test_start <= test_end
        ):
            raise ValueError("discovery, validation and test periods must not overlap")
        if self.data_cutoff > self.created_at:
            raise ValueError("hypothesis data_cutoff cannot follow creation")

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump_json(exclude={"status"})
        return sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class HypothesisObservation:
    session: date
    condition_matched: bool
    forward_excess_return: float
    transaction_cost: float
    drawdown: float
    turnover: float
    regime: str
    signal_time: datetime
    features_available_at: datetime
    outcome_available_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("signal_time", self.signal_time),
            ("features_available_at", self.features_available_at),
            ("outcome_available_at", self.outcome_available_at),
        ):
            _aware(value, name)
        values = (
            self.forward_excess_return,
            self.transaction_cost,
            self.drawdown,
            self.turnover,
        )
        if any(not isfinite(value) for value in values):
            raise ValueError("hypothesis observation values must be finite")
        if self.transaction_cost < 0 or self.turnover < 0 or self.drawdown > 1e-12:
            raise ValueError("cost/turnover must be nonnegative and drawdown nonpositive")

    def visible_at(self, cutoff: datetime) -> bool:
        _aware(cutoff, "cutoff")
        return self.outcome_available_at <= cutoff

    @property
    def pit_valid(self) -> bool:
        return self.features_available_at <= self.signal_time < self.outcome_available_at

    @property
    def net_return(self) -> float:
        return self.forward_excess_return - self.transaction_cost


@dataclass(frozen=True, slots=True)
class ResearchBudgetConfig:
    max_hypotheses_per_run: int = 25
    max_parameter_combinations: int = 100
    max_threshold_combinations: int = 25
    max_horizon_combinations: int = 5

    def __post_init__(self) -> None:
        if min(
            self.max_hypotheses_per_run,
            self.max_parameter_combinations,
            self.max_threshold_combinations,
            self.max_horizon_combinations,
        ) < 1:
            raise ValueError("research budget limits must be positive")


class ResearchBudget:
    def __init__(self, config: ResearchBudgetConfig | None = None) -> None:
        self.config = config or ResearchBudgetConfig()
        self.hypotheses = 0
        self.parameter_combinations = 0
        self.threshold_combinations = 0
        self.horizon_combinations = 0

    def register(
        self,
        *,
        hypotheses: int = 1,
        parameter_combinations: int = 1,
        threshold_combinations: int = 1,
        horizon_combinations: int = 1,
    ) -> None:
        proposed = (
            self.hypotheses + hypotheses,
            self.parameter_combinations + parameter_combinations,
            self.threshold_combinations + threshold_combinations,
            self.horizon_combinations + horizon_combinations,
        )
        limits = (
            self.config.max_hypotheses_per_run,
            self.config.max_parameter_combinations,
            self.config.max_threshold_combinations,
            self.config.max_horizon_combinations,
        )
        if any(value < 0 for value in proposed) or any(
            value > limit for value, limit in zip(proposed, limits, strict=True)
        ):
            raise RuntimeError("hypothesis research budget exceeded")
        (
            self.hypotheses,
            self.parameter_combinations,
            self.threshold_combinations,
            self.horizon_combinations,
        ) = proposed


@dataclass(frozen=True, slots=True)
class HypothesisValidation:
    hypothesis_id: str
    status: HypothesisStatus
    feature_status: ResearchFeatureStatus
    sample_size: int
    validation_sample_size: int
    oos_sample_size: int
    gross_effect_size: float
    after_cost_effect_size: float
    validation_effect: float
    oos_effect: float
    raw_p_value: float
    adjusted_p_value: float
    oos_stability: float
    regime_stability: float
    maximum_drawdown: float
    turnover: float
    transaction_cost_impact: float
    leakage_detected: bool
    real_data_validated: bool
    blockers: tuple[str, ...]
    model_version: str
    data_cutoff: datetime


@dataclass(frozen=True, slots=True)
class HypothesisValidationConfig:
    minimum_sample_size: int = 60
    minimum_oos_sample_size: int = 20
    fdr_threshold: float = 0.05
    minimum_effect_size: float = 0.001
    minimum_oos_stability: float = 0.50
    minimum_regime_stability: float = 0.50
    maximum_drawdown: float = 0.30
    maximum_turnover: float = 2.0
    model_version: str = "hypothesis-validation-v1"

    def __post_init__(self) -> None:
        if self.minimum_sample_size < 30 or self.minimum_oos_sample_size < 10:
            raise ValueError("hypothesis validation sample thresholds are too small")
        fractions = (
            self.fdr_threshold,
            self.minimum_oos_stability,
            self.minimum_regime_stability,
            self.maximum_drawdown,
        )
        if any(not 0 < value <= 1 for value in fractions):
            raise ValueError("hypothesis validation fractions must lie in (0, 1]")
        if self.minimum_effect_size <= 0 or self.maximum_turnover <= 0:
            raise ValueError("effect and turnover thresholds must be positive")


class HypothesisValidationEngine:
    """Chronological validation with FDR and an explicit research-only promotion."""

    def __init__(
        self,
        config: HypothesisValidationConfig | None = None,
        research_budget_config: ResearchBudgetConfig | None = None,
    ) -> None:
        self.config = config or HypothesisValidationConfig()
        self.research_budget_config = research_budget_config or ResearchBudgetConfig()

    def validate_many(
        self,
        hypotheses: tuple[HypothesisDefinition, ...],
        observations: dict[str, tuple[HypothesisObservation, ...]],
        *,
        evaluation_cutoff: datetime,
        real_data_validated: bool = False,
    ) -> tuple[HypothesisValidation, ...]:
        _aware(evaluation_cutoff, "evaluation_cutoff")
        budget = ResearchBudget(self.research_budget_config)
        threshold_sets = {
            tuple(
                (condition.feature, condition.operator, condition.threshold)
                for condition in item.features
            )
            for item in hypotheses
        }
        budget.register(
            hypotheses=len(hypotheses),
            parameter_combinations=len(hypotheses),
            threshold_combinations=len(threshold_sets),
            horizon_combinations=len({item.horizon for item in hypotheses}),
        )
        preliminary = tuple(
            self._evaluate(
                hypothesis,
                observations.get(hypothesis.hypothesis_id, ()),
                evaluation_cutoff=evaluation_cutoff,
                real_data_validated=real_data_validated,
            )
            for hypothesis in hypotheses
        )
        adjusted = benjamini_hochberg([item.raw_p_value for item in preliminary])
        return tuple(
            self._apply_gate(item, q_value)
            for item, q_value in zip(preliminary, adjusted, strict=True)
        )

    def _evaluate(
        self,
        hypothesis: HypothesisDefinition,
        observations: tuple[HypothesisObservation, ...],
        *,
        evaluation_cutoff: datetime,
        real_data_validated: bool,
    ) -> HypothesisValidation:
        ordered = tuple(sorted(observations, key=lambda item: item.session))
        duplicate_sessions = len({item.session for item in ordered}) != len(ordered)
        visible = tuple(item for item in ordered if item.visible_at(evaluation_cutoff))
        leakage = duplicate_sessions or any(not item.pit_valid for item in visible)
        matched = tuple(item for item in visible if item.condition_matched)
        validation = tuple(
            item
            for item in matched
            if hypothesis.validation_period[0] <= item.session <= hypothesis.validation_period[1]
        )
        test = tuple(
            item
            for item in matched
            if hypothesis.test_period[0] <= item.session <= hypothesis.test_period[1]
        )
        validation_values = tuple(item.net_return for item in validation)
        test_values = tuple(item.net_return for item in test)
        raw_p = _one_sided_p_value(validation_values)
        validation_effect = mean(validation_values) if validation_values else 0.0
        oos_effect = mean(test_values) if test_values else 0.0
        gross = mean(item.forward_excess_return for item in matched) if matched else 0.0
        net = mean(item.net_return for item in matched) if matched else 0.0
        transaction_cost = mean(item.transaction_cost for item in matched) if matched else 0.0
        turnover = mean(item.turnover for item in matched) if matched else 0.0
        maximum_drawdown = min((item.drawdown for item in matched), default=0.0)
        stability = _effect_stability(validation_effect, oos_effect)
        regime_stability = _regime_stability(test)
        return HypothesisValidation(
            hypothesis_id=hypothesis.hypothesis_id,
            status=HypothesisStatus.TESTING,
            feature_status=ResearchFeatureStatus.RESEARCH_ONLY,
            sample_size=len(matched),
            validation_sample_size=len(validation),
            oos_sample_size=len(test),
            gross_effect_size=gross,
            after_cost_effect_size=net,
            validation_effect=validation_effect,
            oos_effect=oos_effect,
            raw_p_value=raw_p,
            adjusted_p_value=1.0,
            oos_stability=stability,
            regime_stability=regime_stability,
            maximum_drawdown=maximum_drawdown,
            turnover=turnover,
            transaction_cost_impact=transaction_cost,
            leakage_detected=leakage,
            real_data_validated=real_data_validated,
            blockers=(),
            model_version=self.config.model_version,
            data_cutoff=evaluation_cutoff,
        )

    def _apply_gate(
        self,
        result: HypothesisValidation,
        adjusted_p_value: float,
    ) -> HypothesisValidation:
        blockers: list[str] = []
        if result.leakage_detected:
            blockers.append("point-in-time leakage or duplicate session detected")
        if result.sample_size < self.config.minimum_sample_size:
            blockers.append("minimum sample size failed")
        if result.oos_sample_size < self.config.minimum_oos_sample_size:
            blockers.append("minimum out-of-sample size failed")
        if adjusted_p_value > self.config.fdr_threshold:
            blockers.append("multiple-testing-adjusted significance failed")
        if result.after_cost_effect_size < self.config.minimum_effect_size:
            blockers.append("after-cost economic effect is insufficient")
        if result.oos_effect < self.config.minimum_effect_size:
            blockers.append("out-of-sample effect is insufficient")
        if result.oos_stability < self.config.minimum_oos_stability:
            blockers.append("out-of-sample effect is unstable")
        if result.regime_stability < self.config.minimum_regime_stability:
            blockers.append("regime stability failed")
        if result.maximum_drawdown < -self.config.maximum_drawdown:
            blockers.append("drawdown exceeds research limit")
        if result.turnover > self.config.maximum_turnover:
            blockers.append("turnover exceeds research limit")
        status = HypothesisStatus.REJECTED if blockers else HypothesisStatus.VALIDATED
        feature_status = (
            ResearchFeatureStatus.REJECTED
            if blockers
            else ResearchFeatureStatus.VALIDATED_RESEARCH_FEATURE
        )
        return replace(
            result,
            status=status,
            feature_status=feature_status,
            adjusted_p_value=adjusted_p_value,
            blockers=tuple(blockers),
        )


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    status: PromotionStatus
    blockers: tuple[str, ...]
    requires_manual_approval: bool


class ResearchPromotionGate:
    """Validated research is not production Alpha without real data and approval."""

    def evaluate(
        self,
        validation: HypothesisValidation,
        *,
        manual_approval: bool = False,
    ) -> PromotionDecision:
        blockers = list(validation.blockers)
        if validation.feature_status is not ResearchFeatureStatus.VALIDATED_RESEARCH_FEATURE:
            blockers.append("hypothesis is not a validated research feature")
        if not validation.real_data_validated:
            blockers.append("real point-in-time data validation is missing")
        if blockers:
            return PromotionDecision(PromotionStatus.REJECTED, tuple(dict.fromkeys(blockers)), True)
        if not manual_approval:
            return PromotionDecision(
                PromotionStatus.ELIGIBLE_FOR_MANUAL_REVIEW,
                ("explicit production approval is required",),
                True,
            )
        return PromotionDecision(PromotionStatus.PRODUCTION_APPROVED, (), True)


@dataclass(frozen=True, slots=True)
class SyntheticNoiseResult:
    tested_hypotheses: int
    validated_hypotheses: int
    false_discovery_rate: float
    passed: bool
    random_seed: int


def run_synthetic_noise_test(
    *,
    hypothesis_count: int = 20,
    observation_count: int = 240,
    random_seed: int = 42,
    fdr_limit: float = 0.10,
) -> SyntheticNoiseResult:
    if hypothesis_count < 1 or observation_count < 90:
        raise ValueError("noise test dimensions are too small")
    rng = np.random.default_rng(random_seed)
    start = date(2020, 1, 1)
    hypotheses: list[HypothesisDefinition] = []
    data: dict[str, tuple[HypothesisObservation, ...]] = {}
    cutoff = datetime(2025, 1, 1, tzinfo=UTC)
    for index in range(hypothesis_count):
        hypothesis_id = f"noise-{index:04d}"
        hypotheses.append(
            HypothesisDefinition(
                hypothesis_id=hypothesis_id,
                description="Synthetic noise must not be promoted",
                features=(FeatureCondition(feature="noise", operator=">", threshold=0.0),),
                target="SYNTHETIC",
                benchmark="ZERO",
                horizon=5,
                creator="deterministic-noise-test",
                model_version="noise-test-v1",
                discovery_period=(start, start + timedelta(days=79)),
                validation_period=(start + timedelta(days=80), start + timedelta(days=159)),
                test_period=(start + timedelta(days=160), start + timedelta(days=239)),
                created_at=cutoff,
                data_cutoff=cutoff - timedelta(seconds=1),
                backtest_safety=BacktestSafety.BACKTEST_SAFE,
                status=HypothesisStatus.FORMALIZED,
            )
        )
        matched = rng.random(observation_count) > 0.35
        returns = rng.normal(0.0, 0.01, observation_count)
        items: list[HypothesisObservation] = []
        for position in range(observation_count):
            session = start + timedelta(days=position)
            signal = datetime.combine(session, datetime.min.time(), tzinfo=UTC)
            items.append(
                HypothesisObservation(
                    session=session,
                    condition_matched=bool(matched[position]),
                    forward_excess_return=float(returns[position]),
                    transaction_cost=0.0005,
                    drawdown=-abs(float(returns[position])),
                    turnover=0.1,
                    regime=("RISK_ON" if position % 2 else "NEUTRAL"),
                    signal_time=signal,
                    features_available_at=signal - timedelta(minutes=1),
                    outcome_available_at=signal + timedelta(days=6),
                )
            )
        data[hypothesis_id] = tuple(items)
    engine = HypothesisValidationEngine(
        HypothesisValidationConfig(
            minimum_sample_size=60,
            minimum_oos_sample_size=20,
            fdr_threshold=0.05,
            minimum_effect_size=0.001,
        )
    )
    results = engine.validate_many(tuple(hypotheses), data, evaluation_cutoff=cutoff)
    validated = sum(item.status is HypothesisStatus.VALIDATED for item in results)
    rate = validated / hypothesis_count
    return SyntheticNoiseResult(
        hypothesis_count,
        validated,
        rate,
        rate <= fdr_limit,
        random_seed,
    )


def _one_sided_p_value(values: tuple[float, ...]) -> float:
    if len(values) < 2 or np.isclose(np.std(values, ddof=1), 0.0):
        return 1.0
    statistic = ttest_1samp(values, popmean=0.0, alternative="greater")
    return float(statistic.pvalue) if isfinite(float(statistic.pvalue)) else 1.0


def _effect_stability(validation_effect: float, oos_effect: float) -> float:
    if validation_effect <= 0 or oos_effect <= 0:
        return 0.0
    denominator = max(abs(validation_effect), abs(oos_effect), 1e-12)
    return max(0.0, min(1.0, 1 - abs(validation_effect - oos_effect) / denominator))


def _regime_stability(observations: tuple[HypothesisObservation, ...]) -> float:
    grouped: dict[str, list[float]] = {}
    for item in observations:
        grouped.setdefault(item.regime, []).append(item.net_return)
    if not grouped:
        return 0.0
    return sum(mean(values) > 0 for values in grouped.values()) / len(grouped)

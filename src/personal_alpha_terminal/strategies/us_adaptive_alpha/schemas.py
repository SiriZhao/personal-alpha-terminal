from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from math import isfinite
from typing import Literal


class GateStatus(StrEnum):
    PASSED = "passed"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class SleeveStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ISOLATED = "isolated"
    EXPERIMENTAL = "experimental"


class EvidenceGrade(StrEnum):
    INSUFFICIENT = "insufficient"
    LOW = "low"
    MODERATE = "moderate"
    STRONG = "strong"


class ResearchStage(StrEnum):
    HISTORICAL_RESEARCH = "historical_research"
    LOCKED_OUT_OF_SAMPLE = "locked_out_of_sample"
    FORWARD_OBSERVATION = "forward_observation"
    SHADOW_PORTFOLIO = "shadow_portfolio"
    MANUAL_MICRO_CAPITAL = "manual_micro_capital"
    GRADUAL_SCALE = "gradual_scale"


SignalGrade = Literal["positive", "neutral", "negative", "insufficient"]


@dataclass(frozen=True, slots=True)
class DataGateInput:
    market: str
    quality_status: str
    sample_count: int
    required_sample_count: int = 100
    security_master_ready: bool = False
    point_in_time_universe_ready: bool = False
    trading_calendar_ready: bool = False
    corporate_actions_ready: bool = False
    point_in_time_total_return_ready: bool = False
    source_conflict: bool = False
    stale: bool = False
    as_of_time: datetime | None = None
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DataGateDecision:
    status: GateStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    allowed_for_research: bool
    allowed_for_position_range: bool


@dataclass(frozen=True, slots=True)
class ResearchCapabilities:
    pit_prices: bool = False
    pit_fundamentals: bool = False
    pit_sector_membership: bool = False
    pit_earnings_events: bool = False
    benchmark_history: bool = False
    calibrated_regime: bool = False
    corrected_relationships: bool = False
    conditional_oos_history: bool = False
    defensive_asset_history: bool = False


@dataclass(frozen=True, slots=True)
class SleeveAssessment:
    name: str
    label: str
    status: SleeveStatus
    reason: str
    required_capabilities: tuple[str, ...]
    maximum_capital_weight: float


@dataclass(frozen=True, slots=True)
class ReturnObservation:
    observation_id: str
    event_date: date
    horizon_end_date: date
    forward_return: float
    available_time: datetime
    regime: str = "all"
    is_out_of_sample: bool = False

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("observation_id cannot be empty")
        if self.event_date > self.horizon_end_date:
            raise ValueError("event_date cannot be after horizon_end_date")
        if self.available_time.tzinfo is None:
            raise ValueError("available_time must be timezone-aware")
        if not isfinite(self.forward_return) or self.forward_return <= -1:
            raise ValueError("forward_return must be finite and greater than -100%")


@dataclass(frozen=True, slots=True)
class ConditionalOverlayConfig:
    minimum_sample_size: int = 30
    minimum_effective_sample_size: float = 20.0
    confidence_level: float = 0.95
    prior_alpha: float = 1.0
    prior_beta: float = 1.0
    transaction_cost_bps: float = 10.0
    fdr_alpha: float = 0.10
    maximum_interval_width: float = 0.35
    maximum_data_age_days: int = 7
    evidence_half_life_days: int = 126
    bootstrap_resamples: int = 2_000
    random_seed: int = 41
    require_out_of_sample: bool = True

    def __post_init__(self) -> None:
        if self.minimum_sample_size < 30:
            raise ValueError("minimum_sample_size must be at least 30")
        if self.minimum_effective_sample_size < 2:
            raise ValueError("minimum_effective_sample_size must be at least 2")
        if not 0 < self.confidence_level < 1:
            raise ValueError("confidence_level must be in (0, 1)")
        if self.prior_alpha <= 0 or self.prior_beta <= 0:
            raise ValueError("beta prior parameters must be positive")
        if self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps cannot be negative")
        if not 0 < self.fdr_alpha < 1:
            raise ValueError("fdr_alpha must be in (0, 1)")
        if not 0 < self.maximum_interval_width < 1:
            raise ValueError("maximum_interval_width must be in (0, 1)")
        if self.maximum_data_age_days < 0 or self.evidence_half_life_days < 1:
            raise ValueError("freshness parameters are invalid")
        if self.bootstrap_resamples < 1_000:
            raise ValueError("bootstrap_resamples must be at least 1000")


@dataclass(frozen=True, slots=True)
class ConditionalEvidence:
    hypothesis_id: str
    horizon_days: int
    regime: str
    conditional_sample_size: int
    baseline_sample_size: int
    effective_sample_size: float
    conditional_probability: float | None
    baseline_probability: float | None
    probability_lift: float | None
    odds_ratio: float | None
    lift_lower: float | None
    lift_upper: float | None
    conditional_lower: float | None
    conditional_upper: float | None
    average_return: float | None
    median_return: float | None
    tail_loss_5pct: float | None
    maximum_adverse_return: float | None
    net_expected_return: float | None
    baseline_expected_return: float | None
    conditional_expected_return: float | None
    expected_return_lift: float | None
    mean_return_lower: float | None
    mean_return_upper: float | None
    raw_p_value: float | None
    fdr_q_value: float | None
    calibration_passed: bool
    drift_passed: bool
    data_age_days: int | None
    evidence_decay: float
    grade: EvidenceGrade
    reasons: tuple[str, ...]
    retained_observation_ids: tuple[str, ...]

    @property
    def usable_as_overlay(self) -> bool:
        return self.grade in {EvidenceGrade.MODERATE, EvidenceGrade.STRONG}


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrationObservation:
    predicted_probability: float
    outcome: bool
    observed_on: date


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrationReport:
    status: Literal["calibrated", "uncalibrated"]
    observation_count: int
    brier_score: float | None
    baseline_brier_score: float | None
    calibration_error: float | None
    bins: tuple[tuple[float, float, int], ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProbabilityDriftReport:
    status: Literal["stable", "drifting", "insufficient"]
    reference_count: int
    recent_count: int
    mean_shift: float | None
    positive_rate_shift: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MomentumCrashInput:
    rebound_after_drawdown: float | None = None
    winner_loser_beta_spread: float | None = None
    short_interest_pressure: float | None = None
    return_dispersion: float | None = None
    high_volatility_state: float | None = None
    momentum_factor_drawdown: float | None = None
    valuation_crowding: float | None = None
    industry_concentration: float | None = None
    correlation_spike: float | None = None


@dataclass(frozen=True, slots=True)
class MomentumCrashResult:
    available: bool
    score: float | None
    risk_level: Literal["unavailable", "low", "elevated", "high"]
    momentum_multiplier: float
    total_risk_multiplier: float
    observed_indicators: int
    contributions: dict[str, float]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegimeBudgetInput:
    regime: str
    calibration_status: Literal["calibrated", "score_only"]
    score: float
    probability: float | None
    previous_multiplier: float
    confirmation_count: int
    sessions_since_change: int


@dataclass(frozen=True, slots=True)
class RegimeBudgetDecision:
    display_name: Literal["Market Regime Probability", "Market Regime Score"]
    target_multiplier: float
    applied_multiplier: float
    transition_limited: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SleeveSignal:
    sleeve_name: str
    symbol: str
    signal_grade: SignalGrade
    requested_weight: float
    evidence_score: float
    sector: str
    correlation_cluster: str
    maximum_liquidity_weight: float
    data_as_of: datetime
    trace_ids: tuple[str, ...]
    rationale: tuple[str, ...]
    failure_conditions: tuple[str, ...]
    beta: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("requested_weight", self.requested_weight),
            ("evidence_score", self.evidence_score),
            ("maximum_liquidity_weight", self.maximum_liquidity_weight),
        ):
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.data_as_of.tzinfo is None:
            raise ValueError("data_as_of must be timezone-aware")
        if self.beta is not None and (not isfinite(self.beta) or self.beta < 0):
            raise ValueError("beta must be finite and nonnegative")
        if not self.trace_ids:
            raise ValueError("signal requires trace ids")


@dataclass(frozen=True, slots=True)
class CapitalPreservationConfig:
    maximum_invested_weight: float = 0.80
    maximum_single_name_weight: float = 0.05
    maximum_sector_weight: float = 0.25
    maximum_cluster_weight: float = 0.20
    maximum_top_five_weight: float = 0.25
    maximum_sleeve_weight: float = 0.35
    maximum_experimental_sleeve_weight: float = 0.05
    maximum_beta: float = 1.0
    maximum_daily_weight_change: float = 0.02
    minimum_signal_evidence: float = 0.55
    positive_overlay_limit: float = 0.10
    negative_overlay_limit: float = 0.30

    def __post_init__(self) -> None:
        values = (
            self.maximum_invested_weight,
            self.maximum_single_name_weight,
            self.maximum_sector_weight,
            self.maximum_cluster_weight,
            self.maximum_top_five_weight,
            self.maximum_sleeve_weight,
            self.maximum_experimental_sleeve_weight,
            self.maximum_beta,
            self.maximum_daily_weight_change,
            self.minimum_signal_evidence,
            self.positive_overlay_limit,
            self.negative_overlay_limit,
        )
        if any(not isfinite(item) or item < 0 for item in values):
            raise ValueError("capital-preservation limits must be finite and nonnegative")
        if self.maximum_invested_weight > 1 or self.maximum_single_name_weight > 1:
            raise ValueError("portfolio weights cannot exceed 100%")


@dataclass(frozen=True, slots=True)
class PortfolioRiskSnapshot:
    current_weights: dict[str, float] = field(default_factory=dict)
    sector_weights: dict[str, float] = field(default_factory=dict)
    cluster_weights: dict[str, float] = field(default_factory=dict)
    sleeve_weights: dict[str, float] = field(default_factory=dict)
    portfolio_beta: float | None = None


@dataclass(frozen=True, slots=True)
class EnsembleDecision:
    symbol: str
    sleeve_name: str
    base_requested_weight: float
    conditional_multiplier: float
    regime_multiplier: float
    momentum_crash_multiplier: float
    risk_constrained_weight: float
    suggested_weight_low: float
    suggested_weight_high: float
    final_grade: SignalGrade
    allowed: bool
    constraint_reasons: tuple[str, ...]
    decomposition: dict[str, float]
    trace_ids: tuple[str, ...]
    failure_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnsembleResult:
    data_gate: DataGateDecision
    decisions: tuple[EnsembleDecision, ...]
    cash_weight: float
    total_invested_weight: float
    warnings: tuple[str, ...]
    stage: ResearchStage
    automatic_ordering_enabled: bool = False


@dataclass(frozen=True, slots=True)
class AllocationAsset:
    symbol: str
    score: float
    volatility: float
    cluster: str
    current_weight: float = 0.0


@dataclass(frozen=True, slots=True)
class AllocationResult:
    method: str
    weights: dict[str, float]
    cash_weight: float
    turnover: float
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FactorEvidence:
    name: str
    category: str
    available: bool
    train_ic: tuple[float, ...]
    validation_ic: tuple[float, ...]
    theoretical_weight: float = 1.0
    instability_penalty: float = 0.0

    def __post_init__(self) -> None:
        values = (*self.train_ic, *self.validation_ic)
        if any(not isfinite(item) or not -1 <= item <= 1 for item in values):
            raise ValueError("IC observations must be finite and in [-1, 1]")
        if self.theoretical_weight < 0:
            raise ValueError("theoretical_weight cannot be negative")
        if not 0 <= self.instability_penalty <= 1:
            raise ValueError("instability_penalty must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class FactorWeightingResult:
    candidates: dict[str, dict[str, float]]
    selected_method: str
    selected_weights: dict[str, float]
    validation_score: float | None
    reasons: tuple[str, ...]
    locked_test_used_for_fitting: bool = False


@dataclass(frozen=True, slots=True)
class StageEvidence:
    data_gate_passed: bool
    frozen_parameters: bool
    locked_test_passed: bool
    benchmark_suite_complete: bool
    costs_included: bool
    observation_days: int = 0
    operational_incidents: int = 0
    shadow_days: int = 0
    manual_risk_approval: bool = False


@dataclass(frozen=True, slots=True)
class StageGateDecision:
    current_stage: ResearchStage
    maximum_allowed_stage: ResearchStage
    passed: bool
    blockers: tuple[str, ...]
    automatic_capital_decision_allowed: bool = False

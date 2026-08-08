from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite


class DecisionAction(StrEnum):
    BUY = "BUY"
    ADD = "ADD"
    REDUCE = "REDUCE"
    SELL = "SELL"
    HOLD = "HOLD"
    WATCH = "WATCH"


class DecisionBatchStatus(StrEnum):
    GENERATED = "generated"
    NO_DECISION = "no_decision"
    BLOCKED = "blocked"


class UserDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WATCH = "watch"


@dataclass(frozen=True, slots=True)
class DecisionCandidate:
    stock_id: int
    ticker: str
    permanent_security_id: str
    current_weight: float
    optimized_target_weight: float
    reference_price: float
    factor_score: float
    regime_score: float
    risk_score: float
    probability_lift: float
    probability_sample_size: int
    probability_calibrated: bool
    oos_validated: bool
    as_of_time: datetime
    source_ids: tuple[str, ...]
    rationale: tuple[str, ...]
    risk_factors: tuple[str, ...]
    maximum_shares: int
    lot_size: int = 1
    alpha_validation_status: str = "RESEARCH"
    expected_excess_return: float | None = None
    alpha_confidence: float = 0.0
    alpha_pit_valid: bool = False
    alpha_model_version: str = "unvalidated"
    alpha_data_version: str = "unvalidated"
    portfolio_validation_status: str = "RESEARCH"
    portfolio_model_version: str = "unvalidated"
    risk_constraints_applied: bool = False

    def __post_init__(self) -> None:
        numeric = (
            self.current_weight,
            self.optimized_target_weight,
            self.reference_price,
            self.factor_score,
            self.regime_score,
            self.risk_score,
            self.probability_lift,
        )
        if any(not isfinite(value) for value in numeric):
            raise ValueError("decision candidate values must be finite")
        if self.stock_id <= 0 or not self.ticker.strip() or not self.permanent_security_id.strip():
            raise ValueError("decision candidate requires permanent asset identity")
        if not 0 <= self.current_weight <= 1 or not 0 <= self.optimized_target_weight <= 1:
            raise ValueError("decision weights must be in [0, 1]")
        if self.reference_price <= 0:
            raise ValueError("decision reference price must be positive")
        if not 0 <= self.factor_score <= 100:
            raise ValueError("factor_score must be in [0, 100]")
        if not -100 <= self.regime_score <= 100:
            raise ValueError("regime_score must be in [-100, 100]")
        if not 0 <= self.risk_score <= 100:
            raise ValueError("risk_score must be in [0, 100]")
        if not -1 <= self.probability_lift <= 1:
            raise ValueError("probability_lift must be in [-1, 1]")
        if self.probability_sample_size < 0:
            raise ValueError("probability sample size cannot be negative")
        if self.as_of_time.tzinfo is None:
            raise ValueError("candidate as_of_time must be timezone-aware")
        if not self.source_ids or any(not item.strip() for item in self.source_ids):
            raise ValueError("decision candidate requires source lineage")
        if self.maximum_shares < 0 or self.lot_size < 1:
            raise ValueError("decision share limits are invalid")
        if self.expected_excess_return is not None and not isfinite(
            self.expected_excess_return
        ):
            raise ValueError("expected_excess_return must be finite when present")
        if not 0 <= self.alpha_confidence <= 1:
            raise ValueError("alpha_confidence must be in [0, 1]")
        if (
            not self.alpha_model_version.strip()
            or not self.alpha_data_version.strip()
            or not self.portfolio_model_version.strip()
        ):
            raise ValueError("alpha and portfolio model/data version lineage is required")


@dataclass(frozen=True, slots=True)
class DecisionRecommendation:
    recommendation_id: str
    stock_id: int
    ticker: str
    permanent_security_id: str
    action: DecisionAction
    current_weight: float
    target_weight: float
    quant_score: float
    confidence_score: float
    component_scores: dict[str, float]
    rationale: tuple[str, ...]
    risk_factors: tuple[str, ...]
    evidence_grade: str
    sample_size: int
    source_ids: tuple[str, ...]
    reference_price: float
    suggested_shares: int
    earliest_execution_time: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionBatch:
    portfolio_id: int
    as_of_time: datetime
    status: DecisionBatchStatus
    gate_status: str
    authorization_id: str | None
    data_version: str
    model_version: str
    input_fingerprint: str
    source_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    recommendations: tuple[DecisionRecommendation, ...]

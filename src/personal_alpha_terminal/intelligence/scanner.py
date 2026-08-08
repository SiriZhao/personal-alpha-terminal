from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite, tanh

from personal_alpha_terminal.intelligence.event_study import EventStudyStatistic
from personal_alpha_terminal.intelligence.fusion import (
    SignalFusionConfig,
    ValidatedResearchFeature,
    ValidatedSignalFusion,
)
from personal_alpha_terminal.quant_engine.alpha import AlphaSignal
from personal_alpha_terminal.quant_engine.portfolio.trades import TradeProposal
from personal_alpha_terminal.quant_engine.probability import ConditionalProbability2
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchPurpose,
)


class ScannerMode(StrEnum):
    QUANT_ONLY = "QUANT_ONLY"
    QUANT_PLUS_EVENT = "QUANT_PLUS_EVENT"
    QUANT_PLUS_EVENT_PROBABILITY = "QUANT_PLUS_EVENT_PROBABILITY"
    QUANT_PLUS_EVENT_PLUS_NARRATIVE = "QUANT_PLUS_EVENT_PLUS_NARRATIVE"
    QUANT_FULL_VALIDATED_INTELLIGENCE = "QUANT_FULL_VALIDATED_INTELLIGENCE"


class CandidateStatus(StrEnum):
    ACTIONABLE = "ACTIONABLE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    quant_weight: float = 0.75
    probability_weight: float = 0.15
    event_weight: float = 0.10
    risk_penalty_weight: float = 0.20
    expected_return_scale: float = 0.03
    max_ai_feature_contribution: float = 0.0
    max_event_feature_contribution: float = 0.10
    narrative_weight: float = 0.0
    relationship_weight: float = 0.0
    hypothesis_weight: float = 0.0
    max_narrative_feature_contribution: float = 0.05
    max_relationship_feature_contribution: float = 0.05
    max_hypothesis_feature_contribution: float = 0.05
    model_version: str = "opportunity-scanner-v1"

    def __post_init__(self) -> None:
        weights = (
            self.quant_weight,
            self.probability_weight,
            self.event_weight,
            self.risk_penalty_weight,
            self.max_ai_feature_contribution,
            self.max_event_feature_contribution,
            self.narrative_weight,
            self.relationship_weight,
            self.hypothesis_weight,
            self.max_narrative_feature_contribution,
            self.max_relationship_feature_contribution,
            self.max_hypothesis_feature_contribution,
        )
        if any(not isfinite(value) or value < 0 or value > 1 for value in weights):
            raise ValueError("scanner weights must be finite fractions")
        if self.event_weight > self.max_event_feature_contribution:
            raise ValueError("event contribution exceeds configured guardrail")
        if self.max_ai_feature_contribution != 0:
            raise ValueError("AI features cannot influence candidate ranking")
        if self.narrative_weight > self.max_narrative_feature_contribution:
            raise ValueError("narrative contribution exceeds configured guardrail")
        if self.relationship_weight > self.max_relationship_feature_contribution:
            raise ValueError("relationship contribution exceeds configured guardrail")
        if self.hypothesis_weight > self.max_hypothesis_feature_contribution:
            raise ValueError("hypothesis contribution exceeds configured guardrail")
        if self.expected_return_scale <= 0:
            raise ValueError("expected return scale must be positive")


@dataclass(frozen=True, slots=True)
class OpportunityCandidate:
    decision_id: str
    symbol: str
    status: CandidateStatus
    action_candidate: str
    quant_score: float
    event_score: float
    probability_score: float
    narrative_score: float
    relationship_score: float
    hypothesis_score: float
    risk_score: float
    composite_score: float
    confidence: float
    current_weight: float
    target_weight_candidate: float | None
    positive_drivers: tuple[str, ...]
    negative_drivers: tuple[str, ...]
    historical_analog_summary: str
    risk_flags: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    narrative_context: tuple[str, ...]
    relationship_context: tuple[str, ...]
    hypothesis_context: tuple[str, ...]
    portfolio_constraints: tuple[str, ...]
    lineage: dict[str, object]
    data_readiness: str
    ai_readiness: str
    model_version: str
    data_version: str


class DailyOpportunityScanner:
    """Ranks evidence; only Portfolio Engine/TradeGenerator can make it actionable."""

    def __init__(self, config: ScannerConfig | None = None) -> None:
        self.config = config or ScannerConfig()
        self.fusion = ValidatedSignalFusion(
            SignalFusionConfig(
                expected_return_scale=self.config.expected_return_scale,
                narrative_weight=self.config.narrative_weight,
                relationship_weight=self.config.relationship_weight,
                hypothesis_weight=self.config.hypothesis_weight,
                max_narrative_feature_contribution=(
                    self.config.max_narrative_feature_contribution
                ),
                max_relationship_feature_contribution=(
                    self.config.max_relationship_feature_contribution
                ),
                max_hypothesis_feature_contribution=(
                    self.config.max_hypothesis_feature_contribution
                ),
                max_ai_feature_contribution=self.config.max_ai_feature_contribution,
            )
        )

    def scan(
        self,
        *,
        authorization: ResearchDataAuthorization,
        alpha_signals: tuple[AlphaSignal, ...],
        proposals: tuple[TradeProposal, ...],
        probability_by_symbol: dict[str, ConditionalProbability2],
        event_statistics_by_symbol: dict[str, EventStudyStatistic],
        current_weights: dict[str, float],
        risk_flags_by_symbol: dict[str, tuple[str, ...]],
        mode: ScannerMode,
        ai_ready: bool,
        research_features_by_symbol: (
            dict[str, tuple[ValidatedResearchFeature, ...]] | None
        ) = None,
        lineage_by_symbol: dict[str, dict[str, object]] | None = None,
        portfolio_constraints_by_symbol: dict[str, tuple[str, ...]] | None = None,
        as_of: datetime | None = None,
    ) -> tuple[OpportunityCandidate, ...]:
        decision_permitted = authorization.permits(ResearchPurpose.PORTFOLIO_DECISION)
        proposal_map = {item.ticker: item for item in proposals}
        grouped: dict[str, list[AlphaSignal]] = {}
        for signal in alpha_signals:
            grouped.setdefault(signal.symbol, []).append(signal)
        symbols = sorted(set(grouped) | set(proposal_map))
        output: list[OpportunityCandidate] = []
        research_features_by_symbol = research_features_by_symbol or {}
        lineage_by_symbol = lineage_by_symbol or {}
        portfolio_constraints_by_symbol = portfolio_constraints_by_symbol or {}
        scan_time = as_of or max(
            (item.as_of for item in alpha_signals), default=datetime.now(UTC)
        )
        if scan_time.tzinfo is None or scan_time.utcoffset() is None:
            raise ValueError("opportunity scan time must be timezone-aware")
        for symbol in symbols:
            signals = grouped.get(symbol, [])
            proposal = proposal_map.get(symbol)
            expected = (
                sum(item.expected_excess_return * item.confidence for item in signals)
                / max(1e-12, sum(item.confidence for item in signals))
                if signals
                else 0.0
            )
            confidence = (
                sum(item.confidence for item in signals) / len(signals) if signals else 0.0
            )
            quant_score = _score(expected, self.config.expected_return_scale)
            probability = probability_by_symbol.get(symbol)
            probability_enabled = mode in {
                ScannerMode.QUANT_PLUS_EVENT_PROBABILITY,
                ScannerMode.QUANT_PLUS_EVENT_PLUS_NARRATIVE,
                ScannerMode.QUANT_FULL_VALIDATED_INTELLIGENCE,
            }
            probability_lift = (
                probability.expected_return_lift
                if probability_enabled and probability is not None and probability.valid
                else None
            )
            probability_score = _score(
                probability_lift or 0.0, self.config.expected_return_scale
            )
            event = event_statistics_by_symbol.get(symbol)
            event_return = (
                event.mean_abnormal_return
                if event is not None and event.status.value == "READY"
                else None
            )
            event_enabled = mode is not ScannerMode.QUANT_ONLY
            event_score = (
                _score(event_return or 0.0, self.config.expected_return_scale)
                if event_enabled
                else 50.0
            )
            risk_flags = risk_flags_by_symbol.get(symbol, ())
            risk_score = min(100.0, 20.0 * len(risk_flags))
            event_weight = (
                self.config.event_weight if event_enabled else 0.0
            )
            probability_weight = (
                self.config.probability_weight if probability_enabled else 0.0
            )
            p1_enabled = mode in {
                ScannerMode.QUANT_PLUS_EVENT_PLUS_NARRATIVE,
                ScannerMode.QUANT_FULL_VALIDATED_INTELLIGENCE,
            }
            feature_context = self.fusion.fuse(
                symbol,
                research_features_by_symbol.get(symbol, ()) if p1_enabled else (),
                as_of=scan_time,
            )
            total_positive = (
                self.config.quant_weight
                + probability_weight
                + event_weight
            )
            composite = (
                self.config.quant_weight * quant_score
                + probability_weight * probability_score
                + event_weight * event_score
            ) / max(total_positive, 1e-12)
            composite += feature_context.weighted_contribution
            composite -= self.config.risk_penalty_weight * risk_score
            status = (
                CandidateStatus.ACTIONABLE
                if decision_permitted and proposal is not None
                else CandidateStatus.RESEARCH_ONLY
                if authorization.permits(ResearchPurpose.RESEARCH)
                else CandidateStatus.BLOCKED
            )
            positive_items = [f"validated expected excess return {expected:.4%}"]
            if probability_lift is not None and probability_lift > 0:
                positive_items.append(
                    f"conditional expected-return lift {probability_lift:.4%}"
                )
            if event_return is not None and event_return > 0:
                positive_items.append(f"event abnormal return {event_return:.4%}")
            positive = tuple(positive_items)
            negative_items = list(risk_flags)
            if probability_enabled and probability_lift is None:
                negative_items.append("conditional evidence unavailable or invalid")
            if event_return is None and event_enabled:
                negative_items.append("event intelligence unavailable or insufficient")
            negative_items.extend(feature_context.unavailable_or_research_only)
            negative = tuple(negative_items)
            source_lineage = {
                "portfolio_result": (
                    proposal.model_version if proposal is not None else "UNAVAILABLE"
                ),
                "quant_signals": tuple(
                    f"{item.signal_type}:{item.model_version}:{item.data_version}"
                    for item in signals
                ),
                "conditional_probability": (
                    "VALID" if probability is not None and probability.valid else "UNAVAILABLE"
                ),
                "event_study": (
                    f"{event.horizon}D:n={event.sample_size}"
                    if event is not None
                    else "UNAVAILABLE"
                ),
                "research_feature_ids": tuple(
                    item.feature_id
                    for item in research_features_by_symbol.get(symbol, ())
                ),
                **lineage_by_symbol.get(symbol, {}),
            }
            decision_id = sha256(
                (
                    f"{symbol}|{scan_time.isoformat()}|{self.config.model_version}|"
                    f"{proposal.model_version if proposal else 'RESEARCH_ONLY'}|"
                    f"{json.dumps(source_lineage, sort_keys=True, default=str)}"
                ).encode()
            ).hexdigest()
            output.append(
                OpportunityCandidate(
                    decision_id=decision_id,
                    symbol=symbol,
                    status=status,
                    action_candidate=(
                        proposal.action.value if proposal is not None else "RESEARCH_ONLY"
                    ),
                    quant_score=quant_score,
                    event_score=event_score,
                    probability_score=probability_score,
                    narrative_score=feature_context.narrative_score,
                    relationship_score=feature_context.relationship_score,
                    hypothesis_score=feature_context.hypothesis_score,
                    risk_score=risk_score,
                    composite_score=max(0.0, min(100.0, composite)),
                    confidence=confidence,
                    current_weight=current_weights.get(symbol, 0.0),
                    target_weight_candidate=(
                        proposal.target_weight if proposal is not None else None
                    ),
                    positive_drivers=positive,
                    negative_drivers=negative,
                    historical_analog_summary=(
                        (
                            f"n={event.sample_size}, "
                            f"effective_n={event.effective_sample_size:.1f}, "
                            f"horizon={event.horizon}D"
                        )
                        if event is not None
                        else "unavailable"
                    ),
                    risk_flags=risk_flags,
                    invalidation_conditions=tuple(
                        sorted(
                            {
                                f"{item.signal_type} expires "
                                f"{item.valid_until.isoformat()}"
                                for item in signals
                            }
                        )
                    ),
                    narrative_context=tuple(
                        item
                        for item in feature_context.research_context
                        if item.startswith("NARRATIVE")
                    ),
                    relationship_context=tuple(
                        item
                        for item in feature_context.research_context
                        if item.startswith("RELATIONSHIP")
                    ),
                    hypothesis_context=tuple(
                        item
                        for item in feature_context.research_context
                        if item.startswith("HYPOTHESIS")
                    ),
                    portfolio_constraints=portfolio_constraints_by_symbol.get(symbol, ()),
                    lineage=source_lineage,
                    data_readiness=authorization.decision.status.value,
                    ai_readiness="AI_READY" if ai_ready else "INTELLIGENCE_DEGRADED",
                    model_version=self.config.model_version,
                    data_version=(
                        signals[0].data_version
                        if signals
                        else proposal.data_version
                        if proposal
                        else "UNAVAILABLE"
                    ),
                )
            )
        return tuple(sorted(output, key=lambda item: (-item.composite_score, item.symbol)))


def _score(value: float, scale: float) -> float:
    if not isfinite(value):
        raise ValueError("scanner input must be finite")
    return 50.0 + 50.0 * tanh(value / scale)

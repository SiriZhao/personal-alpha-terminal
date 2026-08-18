"""ROUND71 synchronized portfolio competition and attribution ledger.

The tournament is counterfactual evidence only.  It freezes all inputs needed
to compare variants, accepts outcomes only after the decision timestamp, and
keeps historical, synthetic, forward-shadow, paper, and live evidence
separate.  It never selects a production portfolio or changes execution
policy.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CompetitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PortfolioVariant(StrEnum):
    PURE_QUANT = "PURE_QUANT"
    QUANT_PLUS_PROBABILITY = "QUANT_PLUS_PROBABILITY"
    QUANT_PLUS_LLM = "QUANT_PLUS_LLM"
    QUANT_PLUS_PROBABILITY_PLUS_LLM = "QUANT_PLUS_PROBABILITY_PLUS_LLM"
    FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE = "FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE"


class EvidenceClass(StrEnum):
    HISTORICAL_RESEARCH = "HISTORICAL_RESEARCH"
    SYNTHETIC_STRESS = "SYNTHETIC_STRESS"
    FORWARD_SHADOW = "FORWARD_SHADOW"
    PAPER = "PAPER"
    LIVE = "LIVE"


class OutcomeStatus(StrEnum):
    MISSING = "MISSING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class PromotionVerdict(StrEnum):
    PROMOTE = "PROMOTE"
    RETAIN_CHAMPION = "RETAIN_CHAMPION"
    CHALLENGER_ONLY = "CHALLENGER_ONLY"
    DEMOTE_TO_SHADOW = "DEMOTE_TO_SHADOW"
    BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"
    BLOCKED_DATA_QUALITY = "BLOCKED_DATA_QUALITY"


class AttributionLayer(StrEnum):
    SELECTION_VALUE_ADD = "SELECTION_VALUE_ADD"
    PROBABILITY_VALUE_ADD = "PROBABILITY_VALUE_ADD"
    LLM_VALUE_ADD = "LLM_VALUE_ADD"
    EXPOSURE_CONTROLLER_VALUE_ADD = "EXPOSURE_CONTROLLER_VALUE_ADD"
    RISK_CONTROLLER_VALUE_ADD = "RISK_CONTROLLER_VALUE_ADD"
    COST_IMPACT = "COST_IMPACT"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    return value


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _hash(payload: object) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class DecisionFreeze(CompetitionModel):
    """Immutable decision-time state for one synchronized variant."""

    schema_version: str = "portfolio-competition-freeze-v1"
    decision_id: str
    decision_time: datetime
    information_cutoff: datetime
    variant: PortfolioVariant
    universe_identity: str
    symbols: tuple[str, ...]
    target_weights: dict[str, float]
    target_exposure: float = Field(ge=0, le=1)
    benchmark: str
    execution_assumptions_hash: str
    transaction_cost_model: str
    accounting_rules: str
    input_hash: str
    raw_model_output_hash: str
    portfolio_recommendation_hash: str
    risk_adjustments_hash: str
    model_versions: dict[str, str]
    config_hashes: dict[str, str]
    reason_codes: tuple[str, ...] = ()
    evidence_class: EvidenceClass
    frozen_at: datetime
    freeze_hash: str = ""

    @field_validator("decision_time", "information_cutoff", "frozen_at")
    @classmethod
    def aware_times(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator(
        "decision_id",
        "universe_identity",
        "benchmark",
        "execution_assumptions_hash",
        "transaction_cost_model",
        "accounting_rules",
        "input_hash",
        "raw_model_output_hash",
        "portfolio_recommendation_hash",
        "risk_adjustments_hash",
    )
    @classmethod
    def required_text(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)

    @model_validator(mode="after")
    def validate_freeze(self) -> DecisionFreeze:
        if self.information_cutoff > self.decision_time:
            raise ValueError("information_cutoff cannot follow decision_time")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be non-empty and unique")
        if set(self.target_weights) - set(self.symbols):
            raise ValueError("target_weights contain symbols outside the frozen universe")
        if any(
            not math.isfinite(float(weight)) or weight < 0
            for weight in self.target_weights.values()
        ):
            raise ValueError("target_weights must be finite and long-only")
        if sum(self.target_weights.values()) > 1 + 1e-9:
            raise ValueError("target_weights exceed long-only gross exposure")
        if not self.model_versions or not self.config_hashes:
            raise ValueError("model_versions and config_hashes are required")
        expected = _hash(self.model_dump(exclude={"freeze_hash"}, mode="json"))
        if self.freeze_hash and self.freeze_hash != expected:
            raise ValueError("freeze_hash does not match frozen content")
        object.__setattr__(self, "freeze_hash", expected)
        return self


class TournamentDecision(CompetitionModel):
    schema_version: str = "portfolio-competition-tournament-v1"
    decision_id: str
    decision_time: datetime
    information_cutoff: datetime
    universe_identity: str
    benchmark: str
    execution_assumptions_hash: str
    transaction_cost_model: str
    accounting_rules: str
    variants: tuple[DecisionFreeze, ...]
    tournament_hash: str = ""

    @field_validator("decision_time", "information_cutoff")
    @classmethod
    def tournament_times(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_alignment(self) -> TournamentDecision:
        if self.information_cutoff > self.decision_time:
            raise ValueError("information_cutoff cannot follow decision_time")
        if not self.variants:
            raise ValueError("tournament requires at least one variant")
        by_variant = {item.variant for item in self.variants}
        if len(by_variant) != len(self.variants):
            raise ValueError("tournament cannot contain duplicate variants")
        for item in self.variants:
            if (
                item.decision_id != self.decision_id
                or item.decision_time != self.decision_time
                or item.information_cutoff != self.information_cutoff
                or item.universe_identity != self.universe_identity
                or item.benchmark != self.benchmark
                or item.execution_assumptions_hash != self.execution_assumptions_hash
                or item.transaction_cost_model != self.transaction_cost_model
                or item.accounting_rules != self.accounting_rules
            ):
                raise ValueError("all variants must share frozen alignment fields")
        expected = _hash(self.model_dump(exclude={"tournament_hash"}, mode="json"))
        if self.tournament_hash and self.tournament_hash != expected:
            raise ValueError("tournament_hash does not match frozen content")
        object.__setattr__(self, "tournament_hash", expected)
        return self


class OutcomeRecord(CompetitionModel):
    schema_version: str = "portfolio-competition-outcome-v1"
    outcome_id: str
    decision_id: str
    variant: PortfolioVariant
    outcome_time: datetime
    evidence_class: EvidenceClass
    status: OutcomeStatus
    realized_return: float | None = None
    benchmark_return: float | None = None
    excess_return: float | None = None
    upside_capture: float | None = None
    downside_capture: float | None = None
    max_drawdown: float | None = None
    volatility: float | None = None
    turnover: float | None = None
    expected_cost: float | None = None
    risk_adjusted_return: float | None = None
    benchmark_available: bool = True
    regime: str | None = None
    sample_session_count: int = Field(default=1, ge=0)

    @field_validator("outcome_time")
    @classmethod
    def outcome_time_aware(cls, value: datetime) -> datetime:
        return _aware(value, "outcome_time")

    @field_validator("outcome_id", "decision_id")
    @classmethod
    def outcome_text(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)

    @model_validator(mode="after")
    def validate_outcome(self) -> OutcomeRecord:
        if self.status is OutcomeStatus.COMPLETE:
            required = (
                self.realized_return,
                self.benchmark_return,
                self.excess_return,
                self.turnover,
                self.expected_cost,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "complete outcome requires realized return, benchmark, cost, and turnover"
                )
        if not self.benchmark_available and self.benchmark_return is not None:
            raise ValueError("benchmark_return must be absent when benchmark is unavailable")
        for name in (
            "realized_return",
            "benchmark_return",
            "excess_return",
            "upside_capture",
            "downside_capture",
            "max_drawdown",
            "volatility",
            "turnover",
            "expected_cost",
            "risk_adjusted_return",
        ):
            value = getattr(self, name)
            if value is not None:
                _finite(float(value), name)
        return self


class AttributionRecord(CompetitionModel):
    schema_version: str = "portfolio-competition-attribution-v1"
    decision_id: str
    variant: PortfolioVariant
    layer: AttributionLayer
    evidence_class: EvidenceClass
    sample_n: int = Field(ge=0)
    return_delta: float | None = None
    excess_return_delta: float | None = None
    upside_capture_delta: float | None = None
    downside_capture_delta: float | None = None
    drawdown_delta: float | None = None
    turnover_delta: float | None = None
    risk_adjusted_return_delta: float | None = None
    cost_impact: float | None = None
    confidence_interval: tuple[float, float] | None = None
    status: str = "EVIDENCE_ACCUMULATING"

    @field_validator("decision_id")
    @classmethod
    def attribution_id(cls, value: str) -> str:
        return _text(value, "decision_id")


class PromotionPolicy(CompetitionModel):
    minimum_complete_samples: int = Field(default=120, ge=1)
    minimum_unique_sessions: int = Field(default=40, ge=1)
    minimum_return_delta: float = 0.0
    minimum_excess_delta: float = 0.0
    maximum_drawdown_increase: float = Field(default=0.02, ge=0)
    maximum_turnover_increase: float = Field(default=0.05, ge=0)
    minimum_upside_capture_delta: float = -0.05
    minimum_downside_capture_delta: float = -0.05
    require_forward_or_live: bool = True
    require_confidence_interval_low_non_negative: bool = True
    active_variant: PortfolioVariant | None = None


class VariantEvaluation(CompetitionModel):
    variant: PortfolioVariant
    verdict: PromotionVerdict
    evidence_class: EvidenceClass | None
    complete_samples: int
    unique_sessions: int
    metrics: dict[str, float | None]
    confidence_interval: tuple[float, float] | None = None
    reason_codes: tuple[str, ...]


class CompetitionEvaluation(CompetitionModel):
    schema_version: str = "portfolio-competition-evaluation-v1"
    evaluated_at: datetime
    current_production: PortfolioVariant = PortfolioVariant.PURE_QUANT
    strongest_challenger: PortfolioVariant | None = None
    variant_evaluations: tuple[VariantEvaluation, ...]
    attribution: tuple[AttributionRecord, ...]
    formal_llm_influence: float = Field(ge=0, le=1)
    formal_probability_influence: float = Field(ge=0, le=1)
    evidence_accumulating: bool = True

    @field_validator("evaluated_at")
    @classmethod
    def evaluation_time_aware(cls, value: datetime) -> datetime:
        return _aware(value, "evaluated_at")


class PortfolioCompetitionLedger:
    """Append-only tournament ledger with optional JSONL persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._tournaments: dict[str, TournamentDecision] = {}
        self._outcomes: dict[tuple[str, PortfolioVariant], OutcomeRecord] = {}
        self._attributions: dict[
            tuple[str, PortfolioVariant, AttributionLayer], AttributionRecord
        ] = {}
        if path is not None and path.exists():
            self._load(path)

    def append_tournament(self, tournament: TournamentDecision) -> bool:
        existing = self._tournaments.get(tournament.decision_id)
        if existing is not None:
            if existing.tournament_hash != tournament.tournament_hash:
                raise ValueError("decision_id is immutable and cannot be rewritten")
            return False
        self._tournaments[tournament.decision_id] = tournament
        self._append_json({"kind": "tournament", "payload": tournament.model_dump(mode="json")})
        return True

    def append_outcome(self, outcome: OutcomeRecord) -> bool:
        tournament = self._tournaments.get(outcome.decision_id)
        if tournament is None:
            raise ValueError("outcome references unknown decision_id")
        if outcome.variant not in {item.variant for item in tournament.variants}:
            raise ValueError("outcome variant was not frozen in the tournament")
        decision_time = tournament.decision_time
        if outcome.outcome_time < decision_time:
            raise ValueError("outcome_time cannot precede decision_time")
        key = (outcome.decision_id, outcome.variant)
        existing = self._outcomes.get(key)
        if existing is not None:
            if existing.model_dump(mode="json") != outcome.model_dump(mode="json"):
                raise ValueError("outcome identity is immutable")
            return False
        self._outcomes[key] = outcome
        self._append_json({"kind": "outcome", "payload": outcome.model_dump(mode="json")})
        return True

    def append_attribution(self, attribution: AttributionRecord) -> bool:
        if attribution.decision_id not in self._tournaments:
            raise ValueError("attribution references unknown decision_id")
        key = (attribution.decision_id, attribution.variant, attribution.layer)
        existing = self._attributions.get(key)
        if existing is not None:
            if existing.model_dump(mode="json") != attribution.model_dump(mode="json"):
                raise ValueError("attribution identity is immutable")
            return False
        self._attributions[key] = attribution
        self._append_json({"kind": "attribution", "payload": attribution.model_dump(mode="json")})
        return True

    def tournaments(self) -> tuple[TournamentDecision, ...]:
        return tuple(self._tournaments[key] for key in sorted(self._tournaments))

    def outcomes(self) -> tuple[OutcomeRecord, ...]:
        return tuple(
            self._outcomes[key]
            for key in sorted(self._outcomes, key=lambda item: (item[0], item[1].value))
        )

    def replay_document(self) -> dict[str, object]:
        return {
            "tournaments": [item.model_dump(mode="json") for item in self.tournaments()],
            "outcomes": [item.model_dump(mode="json") for item in self.outcomes()],
            "attributions": [
                item.model_dump(mode="json")
                for item in sorted(
                    self._attributions.values(),
                    key=lambda row: (row.decision_id, row.variant.value, row.layer.value),
                )
            ],
        }

    @classmethod
    def from_document(cls, document: dict[str, object]) -> PortfolioCompetitionLedger:
        """Rebuild a ledger from a deterministic replay document."""

        ledger = cls()
        tournaments = document.get("tournaments", ())
        outcomes = document.get("outcomes", ())
        attributions = document.get("attributions", ())
        if not isinstance(tournaments, list):
            raise ValueError("competition replay tournaments must be a list")
        if not isinstance(outcomes, list):
            raise ValueError("competition replay outcomes must be a list")
        if not isinstance(attributions, list):
            raise ValueError("competition replay document rows must be lists")
        for payload in tournaments:
            if not isinstance(payload, dict):
                raise ValueError("tournament replay row must be an object")
            ledger.append_tournament(TournamentDecision.model_validate(payload))
        for payload in outcomes:
            if not isinstance(payload, dict):
                raise ValueError("outcome replay row must be an object")
            ledger.append_outcome(OutcomeRecord.model_validate(payload))
        for payload in attributions:
            if not isinstance(payload, dict):
                raise ValueError("attribution replay row must be an object")
            ledger.append_attribution(AttributionRecord.model_validate(payload))
        return ledger

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
        policy: PromotionPolicy | None = None,
        formal_llm_influence: float = 0.0,
        formal_probability_influence: float = 0.0,
    ) -> CompetitionEvaluation:
        policy = policy or PromotionPolicy()
        evaluated_at = _aware(evaluated_at, "evaluated_at")
        complete = [
            row
            for row in self.outcomes()
            if row.status is OutcomeStatus.COMPLETE
            and row.outcome_time <= evaluated_at
            and row.evidence_class in {
                EvidenceClass.FORWARD_SHADOW,
                EvidenceClass.PAPER,
                EvidenceClass.LIVE,
            }
        ]
        by_variant: dict[PortfolioVariant, list[OutcomeRecord]] = {}
        for row in complete:
            by_variant.setdefault(row.variant, []).append(row)
        champion_rows = by_variant.get(PortfolioVariant.PURE_QUANT, [])
        evaluations: list[VariantEvaluation] = []
        attribution: list[AttributionRecord] = []
        strongest: tuple[PortfolioVariant, float] | None = None
        for variant in PortfolioVariant:
            if variant is PortfolioVariant.PURE_QUANT:
                continue
            rows = by_variant.get(variant, [])
            metrics = _variant_metrics(rows, champion_rows)
            confidence_interval = _return_delta_interval(rows, champion_rows)
            evidence_class = _common_evidence_class(rows)
            reasons: list[str] = []
            if not rows or len(rows) < policy.minimum_complete_samples:
                verdict = PromotionVerdict.BLOCKED_INSUFFICIENT_EVIDENCE
                reasons.append("INSUFFICIENT_COMPLETE_FORWARD_SAMPLE")
            elif policy.require_forward_or_live and evidence_class not in {
                EvidenceClass.FORWARD_SHADOW,
                EvidenceClass.PAPER,
                EvidenceClass.LIVE,
            }:
                verdict = PromotionVerdict.BLOCKED_DATA_QUALITY
                reasons.append("EVIDENCE_CLASS_NOT_PROMOTABLE")
            elif len({item.outcome_time.date() for item in rows}) < policy.minimum_unique_sessions:
                verdict = PromotionVerdict.BLOCKED_INSUFFICIENT_EVIDENCE
                reasons.append("INSUFFICIENT_UNIQUE_SESSIONS")
            else:
                reasons.extend(_promotion_failures(metrics, policy, confidence_interval))
                verdict = (
                    PromotionVerdict.PROMOTE
                    if not reasons
                    else (
                        PromotionVerdict.DEMOTE_TO_SHADOW
                        if policy.active_variant is variant
                        else PromotionVerdict.CHALLENGER_ONLY
                    )
                )
            evaluation = VariantEvaluation(
                variant=variant,
                verdict=verdict,
                evidence_class=evidence_class,
                complete_samples=len(rows),
                unique_sessions=len({item.outcome_time.date() for item in rows}),
                metrics=metrics,
                confidence_interval=confidence_interval,
                reason_codes=tuple(reasons) or ("PROMOTION_GATES_PASS",),
            )
            evaluations.append(evaluation)
            if metrics.get("risk_adjusted_return_delta") is not None and rows:
                score = float(metrics["risk_adjusted_return_delta"] or 0.0)
                if strongest is None or score > strongest[1]:
                    strongest = (variant, score)
            layer = _layer_for_variant(variant)
            if layer is not None:
                attribution.append(
                    _attribution_from_metrics(
                        variant=variant,
                        layer=layer,
                        rows=rows,
                        metrics=metrics,
                        confidence_interval=confidence_interval,
                    )
                )
        evidence_accumulating = not evaluations or all(
            item.verdict in {
                PromotionVerdict.BLOCKED_INSUFFICIENT_EVIDENCE,
                PromotionVerdict.BLOCKED_DATA_QUALITY,
            }
            for item in evaluations
        )
        return CompetitionEvaluation(
            evaluated_at=evaluated_at,
            strongest_challenger=strongest[0] if strongest else None,
            variant_evaluations=tuple(evaluations),
            attribution=tuple(attribution),
            formal_llm_influence=formal_llm_influence,
            formal_probability_influence=formal_probability_influence,
            evidence_accumulating=evidence_accumulating,
        )

    def _append_json(self, record: dict[str, object]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
                + "\n"
            )

    def _load(self, path: Path) -> None:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            kind = record.get("kind")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("portfolio competition ledger payload must be an object")
            if kind == "tournament":
                tournament = TournamentDecision.model_validate(payload)
                self._tournaments[tournament.decision_id] = tournament
            elif kind == "outcome":
                outcome = OutcomeRecord.model_validate(payload)
                self._outcomes[(outcome.decision_id, outcome.variant)] = outcome
            elif kind == "attribution":
                item = AttributionRecord.model_validate(payload)
                self._attributions[(item.decision_id, item.variant, item.layer)] = item
            else:
                raise ValueError(f"unknown competition ledger record kind: {kind}")


def build_tournament(*freezes: DecisionFreeze) -> TournamentDecision:
    rows = tuple(freezes)
    if not rows:
        raise ValueError("build_tournament requires at least one freeze")
    first = rows[0]
    return TournamentDecision(
        decision_id=first.decision_id,
        decision_time=first.decision_time,
        information_cutoff=first.information_cutoff,
        universe_identity=first.universe_identity,
        benchmark=first.benchmark,
        execution_assumptions_hash=first.execution_assumptions_hash,
        transaction_cost_model=first.transaction_cost_model,
        accounting_rules=first.accounting_rules,
        variants=rows,
    )


def _variant_metrics(
    rows: list[OutcomeRecord], champion_rows: list[OutcomeRecord]
) -> dict[str, float | None]:
    if not rows or not champion_rows:
        return {
            "return_delta": None,
            "excess_return_delta": None,
            "upside_capture_delta": None,
            "downside_capture_delta": None,
            "drawdown_delta": None,
            "turnover_delta": None,
            "risk_adjusted_return_delta": None,
            "cost_impact": None,
        }
    champion_by_key = {(item.decision_id, item.outcome_time.date()): item for item in champion_rows}
    pairs = [
        (row, champion_by_key[(row.decision_id, row.outcome_time.date())])
        for row in rows
        if (row.decision_id, row.outcome_time.date()) in champion_by_key
    ]
    if not pairs:
        return {
            name: None
            for name in (
                "return_delta",
                "excess_return_delta",
                "upside_capture_delta",
                "downside_capture_delta",
                "drawdown_delta",
                "turnover_delta",
                "risk_adjusted_return_delta",
                "cost_impact",
            )
        }
    return {
        "return_delta": mean(
            float(row.realized_return or 0) - float(base.realized_return or 0)
            for row, base in pairs
        ),
        "excess_return_delta": mean(
            float(row.excess_return or 0) - float(base.excess_return or 0)
            for row, base in pairs
        ),
        "upside_capture_delta": _mean_delta(pairs, "upside_capture"),
        "downside_capture_delta": _mean_delta(pairs, "downside_capture"),
        "drawdown_delta": _mean_delta(pairs, "max_drawdown"),
        "turnover_delta": _mean_delta(pairs, "turnover"),
        "risk_adjusted_return_delta": _mean_delta(pairs, "risk_adjusted_return"),
        "cost_impact": _mean_delta(pairs, "expected_cost"),
    }


def _mean_delta(pairs: list[tuple[OutcomeRecord, OutcomeRecord]], name: str) -> float | None:
    values = [
        float(getattr(row, name)) - float(getattr(base, name))
        for row, base in pairs
        if getattr(row, name) is not None and getattr(base, name) is not None
    ]
    return mean(values) if values else None


def _return_delta_interval(
    rows: list[OutcomeRecord], champion_rows: list[OutcomeRecord]
) -> tuple[float, float] | None:
    """Deterministic paired normal-approximation interval; never inferred for n<2."""

    champion_by_key = {(item.decision_id, item.outcome_time.date()): item for item in champion_rows}
    deltas = [
        float(row.realized_return or 0) - float(base.realized_return or 0)
        for row in rows
        if (base := champion_by_key.get((row.decision_id, row.outcome_time.date()))) is not None
    ]
    if len(deltas) < 2:
        return None
    center = mean(deltas)
    variance = sum((value - center) ** 2 for value in deltas) / (len(deltas) - 1)
    margin = 1.96 * math.sqrt(variance / len(deltas))
    return (center - margin, center + margin)


def _common_evidence_class(rows: list[OutcomeRecord]) -> EvidenceClass | None:
    classes = {item.evidence_class for item in rows}
    return next(iter(classes)) if len(classes) == 1 else None


def _promotion_failures(
    metrics: dict[str, float | None],
    policy: PromotionPolicy,
    confidence_interval: tuple[float, float] | None,
) -> list[str]:
    reasons: list[str] = []
    if (metrics.get("return_delta") or 0.0) < policy.minimum_return_delta:
        reasons.append("RETURN_DELTA_BELOW_THRESHOLD")
    if (metrics.get("excess_return_delta") or 0.0) < policy.minimum_excess_delta:
        reasons.append("EXCESS_RETURN_DELTA_BELOW_THRESHOLD")
    if (metrics.get("drawdown_delta") or 0.0) > policy.maximum_drawdown_increase:
        reasons.append("DRAWDOWN_REGRESSION")
    if (metrics.get("turnover_delta") or 0.0) > policy.maximum_turnover_increase:
        reasons.append("TURNOVER_REGRESSION")
    upside_delta = metrics.get("upside_capture_delta")
    if upside_delta is not None and float(upside_delta) < policy.minimum_upside_capture_delta:
        reasons.append("UPSIDE_CAPTURE_REGRESSION")
    downside_delta = metrics.get("downside_capture_delta")
    if (
        downside_delta is not None
        and float(downside_delta) < policy.minimum_downside_capture_delta
    ):
        reasons.append("DOWNSIDE_PROTECTION_REGRESSION")
    if (
        policy.require_confidence_interval_low_non_negative
        and confidence_interval is not None
        and confidence_interval[0] < 0
    ):
        reasons.append("CONFIDENCE_INTERVAL_CROSSES_ZERO")
    return reasons


def _layer_for_variant(variant: PortfolioVariant) -> AttributionLayer | None:
    return {
        PortfolioVariant.QUANT_PLUS_PROBABILITY: AttributionLayer.PROBABILITY_VALUE_ADD,
        PortfolioVariant.QUANT_PLUS_LLM: AttributionLayer.LLM_VALUE_ADD,
        PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM: AttributionLayer.LLM_VALUE_ADD,
        PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE: (
            AttributionLayer.EXPOSURE_CONTROLLER_VALUE_ADD
        ),
    }.get(variant)


def _attribution_from_metrics(
    *,
    variant: PortfolioVariant,
    layer: AttributionLayer,
    rows: list[OutcomeRecord],
    metrics: dict[str, float | None],
    confidence_interval: tuple[float, float] | None,
) -> AttributionRecord:
    evidence_class = _common_evidence_class(rows) or EvidenceClass.FORWARD_SHADOW
    return AttributionRecord(
        decision_id=rows[0].decision_id if rows else "NO_DECISION",
        variant=variant,
        layer=layer,
        evidence_class=evidence_class,
        sample_n=len(rows),
        return_delta=metrics.get("return_delta"),
        excess_return_delta=metrics.get("excess_return_delta"),
        upside_capture_delta=metrics.get("upside_capture_delta"),
        downside_capture_delta=metrics.get("downside_capture_delta"),
        drawdown_delta=metrics.get("drawdown_delta"),
        turnover_delta=metrics.get("turnover_delta"),
        risk_adjusted_return_delta=metrics.get("risk_adjusted_return_delta"),
        cost_impact=metrics.get("cost_impact"),
        confidence_interval=confidence_interval,
        status="EVIDENCE_ACCUMULATING" if len(rows) < 120 else "MEASURED",
    )

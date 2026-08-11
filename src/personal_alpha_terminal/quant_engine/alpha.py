from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite


class AlphaValidationStatus(StrEnum):
    RESEARCH = "RESEARCH"
    VALIDATING = "VALIDATING"
    TESTED = "TESTED"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    DISABLED = "DISABLED"


class AlphaDataQuality(StrEnum):
    VALID = "VALID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    BLOCKED = "BLOCKED"
    NOT_VALIDATED = "NOT_VALIDATED"


@dataclass(frozen=True, slots=True)
class AlphaSignal:
    symbol: str
    as_of: datetime
    signal_type: str
    expected_excess_return: float
    horizon: int
    raw_signal: float
    normalized_signal: float
    confidence: float
    confidence_calibrated: bool
    sample_size: int
    statistical_strength: float
    economic_strength: float
    decay_half_life: float | None
    valid_until: datetime
    data_quality: AlphaDataQuality
    pit_valid: bool
    validation_status: AlphaValidationStatus
    model_version: str
    data_version: str
    evidence_coverage: float = 1.0
    calibration_id: str | None = None

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("alpha timestamps must be timezone-aware")
        if self.valid_until <= self.as_of:
            raise ValueError("alpha valid_until must follow as_of")
        numeric = (
            self.expected_excess_return,
            self.raw_signal,
            self.normalized_signal,
            self.confidence,
            self.statistical_strength,
            self.economic_strength,
            self.evidence_coverage,
        )
        if any(not isfinite(value) for value in numeric):
            raise ValueError("alpha numeric values must be finite")
        if not 0 <= self.confidence <= 1:
            raise ValueError("alpha confidence must be in [0, 1]")
        if not 0 <= self.evidence_coverage <= 1:
            raise ValueError("alpha evidence coverage must be in [0, 1]")
        if self.horizon < 1 or self.sample_size < 0:
            raise ValueError("alpha horizon/sample size is invalid")
        if not self.symbol or not self.model_version or not self.data_version:
            raise ValueError("alpha identity and lineage are required")

    def production_eligible(self, decision_time: datetime) -> bool:
        '''Return whether deterministic alpha may enter the production chain.

        Probability calibration is deliberately not a prerequisite here. The
        immutable model approval owns OOS/PIT/cost validation; an optional
        probability artifact may annotate confidence, but cannot enable or
        disable the deterministic expected-return signal.
        '''

        return (
            self.validation_status is AlphaValidationStatus.PRODUCTION_APPROVED
            and self.data_quality is AlphaDataQuality.VALID
            and self.pit_valid
            and self.as_of <= decision_time <= self.valid_until
        )


@dataclass(frozen=True, slots=True)
class ResearchRunManifest:
    data_version: str
    model_version: str
    config_version: str
    git_commit: str
    as_of: datetime
    random_seed: int

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), default=str, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()


class UnifiedAlphaEngine:
    """Converts validated alpha evidence to expected-return space.

    It never emits BUY/SELL or target weights.  Research and unvalidated signals
    remain inspectable but are excluded from production decisions.
    """

    def for_decision(
        self,
        signals: tuple[AlphaSignal, ...],
        *,
        decision_time: datetime,
    ) -> tuple[AlphaSignal, ...]:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        eligible = tuple(
            item for item in signals if item.production_eligible(decision_time)
        )
        return tuple(
            sorted(
                eligible,
                key=lambda item: (item.symbol, item.horizon, item.signal_type),
            )
        )

    def aggregate_expected_return(
        self,
        signals: tuple[AlphaSignal, ...],
        *,
        decision_time: datetime,
    ) -> dict[tuple[str, int], float]:
        eligible = self.for_decision(signals, decision_time=decision_time)
        grouped: dict[tuple[str, int], list[AlphaSignal]] = {}
        for signal in eligible:
            grouped.setdefault((signal.symbol, signal.horizon), []).append(signal)
        output: dict[tuple[str, int], float] = {}
        for key, items in grouped.items():
            denominator = sum(item.evidence_coverage for item in items)
            if denominator <= 0:
                continue
            output[key] = sum(
                item.expected_excess_return * item.evidence_coverage for item in items
            ) / denominator
        return output

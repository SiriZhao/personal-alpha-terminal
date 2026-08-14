from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import cast

import pandas as pd

from personal_alpha_terminal.models import ModelApprovalRecord
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.factors.cross_sectional import (
    FactorSpec,
    process_cross_section,
)
from personal_alpha_terminal.quant_engine.factors.features import compute_price_features
from personal_alpha_terminal.quant_engine.model_registry import fingerprint_parameters
from personal_alpha_terminal.quant_engine.validation_artifacts import (
    ProbabilityCalibrationArtifact,
)


@dataclass(frozen=True, slots=True)
class USAdaptiveAlphaCoreV1Config:
    momentum_lookback: int = 252
    momentum_skip: int = 21
    trend_window: int = 126
    volatility_window: int = 63
    horizon_sessions: int = 21
    minimum_cross_section: int = 5
    momentum_coefficient: float = 0.006
    trend_coefficient: float = 0.003
    low_volatility_coefficient: float = 0.002
    quality_coefficient: float = 0.0

    @property
    def parameter_fingerprint(self) -> str:
        return fingerprint_parameters(asdict(self))

    @property
    def history_requirements(self) -> tuple[dict[str, object], ...]:
        """Explicit history contract derived from active factor definitions."""
        return (
            {
                "factor": "momentum_12_1",
                "lookback_sessions": self.momentum_lookback,
                "warmup_sessions": self.momentum_skip,
                "effective_required_sessions": self.momentum_lookback + 1,
            },
            {
                "factor": "trend_slope",
                "lookback_sessions": self.trend_window,
                "warmup_sessions": 0,
                "effective_required_sessions": self.trend_window,
            },
            {
                "factor": "volatility",
                "lookback_sessions": self.volatility_window,
                "warmup_sessions": 1,
                "effective_required_sessions": self.volatility_window + 1,
            },
        )

    @property
    def required_history_sessions(self) -> int:
        return max(
            int(cast(int, item["effective_required_sessions"]))
            for item in self.history_requirements
        )


@dataclass(frozen=True, slots=True)
class StrategyFactorSnapshot:
    symbol: str
    components: dict[str, float]
    composite: float
    rank: int
    expected_alpha: float
    evidence_coverage: float
    status: str
    raw_values: dict[str, float] = field(default_factory=dict)
    winsorized_values: dict[str, float] = field(default_factory=dict)
    neutralized_values: dict[str, float] = field(default_factory=dict)
    neutralization_evidence: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StrategyAlphaResult:
    signals: tuple[AlphaSignal, ...]
    disabled_components: tuple[str, ...]
    parameter_fingerprint: str
    factors: tuple[StrategyFactorSnapshot, ...] = ()


class USAdaptiveAlphaCoreV1:
    """Deterministic medium-term US alpha model with explicit validation state.

    Engineering-default coefficients are research-only. They cannot enter production
    unless an approval record matches the exact parameter and data fingerprints.
    """

    model_id = "USAdaptiveAlphaCoreV1"
    version = "1.0.0"

    def __init__(self, config: USAdaptiveAlphaCoreV1Config | None = None) -> None:
        self.config = config or USAdaptiveAlphaCoreV1Config()

    def generate(
        self,
        *,
        prices: pd.DataFrame,
        metadata: pd.DataFrame,
        decision_time: datetime,
        data_version: str,
        approval: ModelApprovalRecord | None,
        operational_approval_hash: str | None = None,
        calibration: ProbabilityCalibrationArtifact | None = None,
        fundamentals: pd.DataFrame | None = None,
        allow_degraded_neutralization: bool = False,
    ) -> StrategyAlphaResult:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        features = compute_price_features(
            prices,
            information_cutoff=decision_time,
            momentum_lookback=self.config.momentum_lookback,
            momentum_skip=self.config.momentum_skip,
            trend_window=self.config.trend_window,
            volatility_window=self.config.volatility_window,
        )
        if len(features) < self.config.minimum_cross_section:
            return StrategyAlphaResult(
                (), ("price_cross_section",), self.config.parameter_fingerprint, ()
            )
        metadata_for_merge = metadata.drop(
            columns=["ticker"],
            errors="ignore",
        )
        observations = features.merge(
            metadata_for_merge,
            on="permanent_security_id",
            how="left",
        )
        specs = [
            FactorSpec(
                "momentum_12_1",
                "high",
                minimum_observations=self.config.minimum_cross_section,
            ),
            FactorSpec(
                "trend_slope",
                "high",
                minimum_observations=self.config.minimum_cross_section,
            ),
            FactorSpec("volatility", "low", minimum_observations=self.config.minimum_cross_section),
        ]
        disabled: list[str] = []
        if fundamentals is not None and self.config.quality_coefficient != 0:
            observations = observations.merge(
                fundamentals, on="permanent_security_id", how="left", suffixes=("", "_fund")
            )
            if "quality" in observations:
                specs.append(
                    FactorSpec(
                        "quality", "high", minimum_observations=self.config.minimum_cross_section
                    )
                )
            else:
                disabled.append("quality")
        else:
            disabled.append("quality")
        processed = process_cross_section(
            observations,
            tuple(specs),
            as_of=decision_time,
            minimum_required_factors=3,
            allow_degraded_neutralization=allow_degraded_neutralization,
        )
        parameter_fingerprint = self.config.parameter_fingerprint
        production = bool(
            approval is not None
            and approval.parameter_fingerprint == parameter_fingerprint
        )
        provisional_operational = bool(
            not production and operational_approval_hash
        )
        calibration_data_version = approval.data_version if approval is not None else data_version
        calibrated = bool(
            calibration is not None
            and calibration.locked_oos
            and calibration.identity.alpha_model_version == f"{self.model_id}:{self.version}"
            and calibration.identity.alpha_data_version == calibration_data_version
            and calibration.identity.strategy_parameter_hash == parameter_fingerprint
        )
        allowed_statuses = {"VALID"}
        if allow_degraded_neutralization:
            allowed_statuses.add("DEGRADED")
        if (
            production or provisional_operational
        ) and any(status.value not in allowed_statuses for status in processed.statuses.values()):
            return StrategyAlphaResult(
                (),
                tuple(
                    sorted(
                        set(disabled)
                        | (
                            {"neutralization:degraded"}
                            if any(
                                status.value == "DEGRADED"
                                for status in processed.statuses.values()
                            )
                            else set()
                        )
                        | {
                            f"{name}:{status.value}"
                            for name, status in processed.statuses.items()
                            if status.value not in allowed_statuses
                        }
                    )
                ),
                parameter_fingerprint,
                (),
            )
        signals: list[AlphaSignal] = []
        factor_rows: list[StrategyFactorSnapshot] = []
        for _, row in processed.frame.iterrows():
            if not bool(row["eligible"]):
                continue
            components = {
                "momentum": float(row["momentum_12_1__normalized"]),
                "trend": float(row["trend_slope__normalized"]),
                "low_volatility": float(row["volatility__normalized"]),
            }
            expected = (
                components["momentum"] * self.config.momentum_coefficient
                + components["trend"] * self.config.trend_coefficient
                + components["low_volatility"] * self.config.low_volatility_coefficient
            )
            if "quality__normalized" in row and pd.notna(row["quality__normalized"]):
                components["quality"] = float(row["quality__normalized"])
                expected += components["quality"] * self.config.quality_coefficient
            coverage = float(row["factor_coverage"])
            raw_values = {
                spec.name: float(row[f"{spec.name}__raw"])
                for spec in specs
                if pd.notna(row.get(f"{spec.name}__raw"))
            }
            winsorized_values = {
                spec.name: float(row[f"{spec.name}__winsorized"])
                for spec in specs
                if pd.notna(row.get(f"{spec.name}__winsorized"))
            }
            factor_rows.append(
                StrategyFactorSnapshot(
                    symbol=str(row["ticker"]),
                    components=components,
                    composite=sum(components.values()) / len(components),
                    rank=0,
                    expected_alpha=expected,
                    evidence_coverage=min(1.0, coverage),
                    status=(
                        "PRODUCTION_APPROVED"
                        if production
                        else "PROVISIONAL_OPERATIONAL_APPROVED"
                        if provisional_operational
                        else "DIAGNOSTIC_ONLY"
                    ),
                    raw_values=raw_values,
                    winsorized_values=winsorized_values,
                    neutralized_values=components,
                    neutralization_evidence={
                        name: asdict(evidence)
                        for name, evidence in processed.neutralization.items()
                    },
                )
            )
            signals.append(
                AlphaSignal(
                    symbol=str(row["ticker"]),
                    as_of=decision_time,
                    signal_type="quality_constrained_medium_term_momentum",
                    expected_excess_return=expected,
                    horizon=self.config.horizon_sessions,
                    raw_signal=float(row["momentum_12_1__raw"]),
                    normalized_signal=sum(components.values()) / len(components),
                    confidence=(min(1.0, coverage) if calibrated else 0.0),
                    confidence_calibrated=calibrated,
                    sample_size=len(processed.frame),
                    statistical_strength=min(1.0, len(processed.frame) / 100),
                    economic_strength=min(1.0, abs(expected) / 0.05),
                    decay_half_life=float(self.config.horizon_sessions),
                    valid_until=decision_time + timedelta(days=35),
                    data_quality=AlphaDataQuality.VALID,
                    pit_valid=True,
                    validation_status=(
                        AlphaValidationStatus.PRODUCTION_APPROVED
                        if production
                        else AlphaValidationStatus.PROVISIONAL_OPERATIONAL_APPROVED
                        if provisional_operational
                        else AlphaValidationStatus.RESEARCH
                    ),
                    model_version=f"{self.model_id}:{self.version}:{parameter_fingerprint[:12]}",
                    data_version=data_version,
                    evidence_coverage=min(1.0, coverage),
                    calibration_id=(
                        calibration.calibration_id
                        if calibrated and calibration
                        else None
                    ),
                    operational_approval_hash=(
                        operational_approval_hash
                        if provisional_operational
                        else None
                    ),
                )
            )
        ranked = sorted(factor_rows, key=lambda item: (-item.expected_alpha, item.symbol))
        factor_rows = [
            StrategyFactorSnapshot(
                symbol=item.symbol,
                components=item.components,
                composite=item.composite,
                rank=index,
                expected_alpha=item.expected_alpha,
                evidence_coverage=item.evidence_coverage,
                status=item.status,
                raw_values=item.raw_values,
                winsorized_values=item.winsorized_values,
                neutralized_values=item.neutralized_values,
                neutralization_evidence=item.neutralization_evidence,
            )
            for index, item in enumerate(ranked, start=1)
        ]
        return StrategyAlphaResult(
            tuple(signals),
            tuple(
                sorted(
                    set(disabled)
                    | (
                        {"neutralization:degraded"}
                        if any(
                            status.value == "DEGRADED"
                            for status in processed.statuses.values()
                        )
                        else set()
                    )
                )
            ),
            parameter_fingerprint,
            tuple(factor_rows),
        )

"""ROUND24 factor-crash diagnostics (D9).

Crowding, dispersion collapse, momentum reversal and correlation-spike
diagnostics.  Diagnostics only: they surface risk, they never change
alpha or weights.
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_VERSION = "factor-crowding-v1"


@dataclass(frozen=True, slots=True)
class FactorCrashDiagnostics:
    factor_concentration_hhi: float | None
    dispersion_collapse_ratio: float | None
    momentum_reversal_flag: bool
    correlation_spike_flag: bool
    single_factor_dominance: str | None
    warnings: tuple[str, ...]
    model_version: str = MODEL_VERSION

    def document(self) -> dict[str, object]:
        return {
            "factor_concentration_hhi": self.factor_concentration_hhi,
            "dispersion_collapse_ratio": self.dispersion_collapse_ratio,
            "momentum_reversal_flag": self.momentum_reversal_flag,
            "correlation_spike_flag": self.correlation_spike_flag,
            "single_factor_dominance": self.single_factor_dominance,
            "warnings": list(self.warnings),
            "model_version": self.model_version,
        }


def diagnose_factor_crash_risk(
    *,
    factor_exposures: dict[str, float],
    cross_sectional_dispersion: float | None,
    dispersion_reference: float | None,
    momentum_recent_return: float | None,
    average_correlation: float | None,
) -> FactorCrashDiagnostics:
    """Compute crowding / dispersion / reversal / correlation diagnostics."""

    warnings: list[str] = []
    total = sum(abs(value) for value in factor_exposures.values())
    hhi = (
        sum((value / total) ** 2 for value in factor_exposures.values())
        if total > 0 and factor_exposures
        else None
    )
    dominant: str | None = None
    if factor_exposures:
        dominant = max(factor_exposures, key=lambda key: abs(factor_exposures[key]))
        if hhi is not None and hhi > 0.6:
            warnings.append(
                f"FACTOR_CROWDING: single factor {dominant} dominates (HHI={hhi:.2f})"
            )
    collapse_ratio: float | None = None
    if (
        cross_sectional_dispersion is not None
        and dispersion_reference is not None
        and dispersion_reference > 0
    ):
        collapse_ratio = cross_sectional_dispersion / dispersion_reference
        if collapse_ratio < 0.5:
            warnings.append("FACTOR_DISPERSION_COLLAPSE")
    reversal = momentum_recent_return is not None and momentum_recent_return < -0.10
    if reversal:
        warnings.append("MOMENTUM_REVERSAL")
    correlation_spike = average_correlation is not None and average_correlation > 0.75
    if correlation_spike:
        warnings.append("CORRELATION_SPIKE")
    return FactorCrashDiagnostics(
        factor_concentration_hhi=round(hhi, 4) if hhi is not None else None,
        dispersion_collapse_ratio=(
            round(collapse_ratio, 4) if collapse_ratio is not None else None
        ),
        momentum_reversal_flag=reversal,
        correlation_spike_flag=correlation_spike,
        single_factor_dominance=dominant if hhi is not None and hhi > 0.6 else None,
        warnings=tuple(warnings),
    )

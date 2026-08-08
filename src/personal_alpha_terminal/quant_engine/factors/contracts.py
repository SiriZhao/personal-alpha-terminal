from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from numbers import Real

from personal_alpha_terminal.quant_engine.factors.cross_sectional import FactorSignalStatus


@dataclass(frozen=True, slots=True)
class FactorObservation:
    """Auditable point-in-time output of one cross-sectional factor."""

    symbol: str
    as_of: datetime
    available_time: datetime
    data_version: str
    factor_version: str
    raw_value: float
    winsorized_value: float
    normalized_value: float
    coverage: float
    quality_status: FactorSignalStatus

    def __post_init__(self) -> None:
        if (
            not self.symbol.strip()
            or not self.data_version.strip()
            or not self.factor_version.strip()
        ):
            raise ValueError("factor observation identifiers are required")
        if self.as_of.tzinfo is None or self.available_time.tzinfo is None:
            raise ValueError("factor timestamps must be timezone-aware")
        if self.available_time > self.as_of:
            raise ValueError("factor observation cannot use information unavailable at as_of")
        if not 0 <= self.coverage <= 1:
            raise ValueError("factor coverage must be in [0, 1]")
        values = (self.raw_value, self.winsorized_value, self.normalized_value)
        if self.quality_status is FactorSignalStatus.VALID and any(
            not isfinite(value) for value in values
        ):
            raise ValueError("valid factor observations require finite values")


def observations_from_cross_section(
    *,
    frame_rows: tuple[dict[str, object], ...],
    factor_name: str,
    factor_version: str,
    data_version: str,
    as_of: datetime,
    status: FactorSignalStatus,
    coverage: float,
) -> tuple[FactorObservation, ...]:
    observations: list[FactorObservation] = []
    for row in frame_rows:
        raw = row.get(f"{factor_name}__raw")
        winsorized = row.get(f"{factor_name}__winsorized")
        normalized = row.get(f"{factor_name}__normalized")
        available_time = row.get("available_at")
        if not (
            isinstance(raw, Real)
            and isinstance(winsorized, Real)
            and isinstance(normalized, Real)
            and isinstance(available_time, datetime)
        ):
            continue
        observations.append(
            FactorObservation(
                symbol=str(row["permanent_security_id"]),
                as_of=as_of,
                available_time=available_time,
                data_version=data_version,
                factor_version=factor_version,
                raw_value=float(raw),
                winsorized_value=float(winsorized),
                normalized_value=float(normalized),
                coverage=coverage,
                quality_status=status,
            )
        )
    return tuple(observations)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import numpy as np
import pandas as pd


class FactorSignalStatus(StrEnum):
    VALID = "VALID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    BLOCKED = "BLOCKED"
    NOT_VALIDATED = "NOT_VALIDATED"


@dataclass(frozen=True, slots=True)
class FactorSpec:
    name: str
    direction: str = "high"
    lower_percentile: float = 0.01
    upper_percentile: float = 0.99
    minimum_observations: int = 5
    sector_neutral: bool = True
    size_neutral: bool = True

    def __post_init__(self) -> None:
        if self.direction not in {"high", "low"}:
            raise ValueError("factor direction must be high or low")
        if not 0 <= self.lower_percentile < self.upper_percentile <= 1:
            raise ValueError("winsorization percentiles are invalid")
        if self.minimum_observations < 3:
            raise ValueError("minimum_observations must be at least three")


@dataclass(frozen=True, slots=True)
class FactorCrossSectionResult:
    frame: pd.DataFrame
    statuses: dict[str, FactorSignalStatus]
    coverage: dict[str, float]
    warnings: tuple[str, ...]
    as_of: datetime


def process_cross_section(
    observations: pd.DataFrame,
    specs: tuple[FactorSpec, ...],
    *,
    as_of: datetime,
    minimum_required_factors: int = 2,
) -> FactorCrossSectionResult:
    """Causal raw -> winsorized -> robust z -> neutralized factor pipeline."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    required = {"permanent_security_id", "available_at", *(spec.name for spec in specs)}
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(f"factor cross-section misses columns: {sorted(missing)}")
    frame = observations.copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    frame = frame.loc[frame["available_at"] <= cutoff]
    frame = (
        frame.sort_values(["permanent_security_id", "available_at"])
        .groupby("permanent_security_id", as_index=False, sort=False)
        .tail(1)
        .set_index("permanent_security_id", drop=False)
    )
    statuses: dict[str, FactorSignalStatus] = {}
    coverage: dict[str, float] = {}
    warnings: list[str] = []
    output = frame.copy()
    for spec in specs:
        raw = pd.to_numeric(frame[spec.name], errors="coerce").replace([np.inf, -np.inf], np.nan)
        coverage[spec.name] = float(raw.notna().mean()) if len(raw) else 0.0
        output[f"{spec.name}__raw"] = raw
        valid = raw.dropna()
        if len(valid) < spec.minimum_observations:
            statuses[spec.name] = FactorSignalStatus.INSUFFICIENT_DATA
            output[f"{spec.name}__winsorized"] = np.nan
            output[f"{spec.name}__normalized"] = np.nan
            continue
        lower, upper = valid.quantile([spec.lower_percentile, spec.upper_percentile])
        winsorized = raw.clip(float(lower), float(upper))
        output[f"{spec.name}__winsorized"] = winsorized
        signal = _robust_zscore(winsorized) * (1.0 if spec.direction == "high" else -1.0)
        neutralized = signal.copy()
        if spec.sector_neutral:
            if "sector" not in frame or frame["sector"].isna().all():
                warnings.append(f"{spec.name}: sector exposure is not neutralized")
                statuses[spec.name] = FactorSignalStatus.NOT_VALIDATED
            else:
                neutralized = _within_group_center(neutralized, frame["sector"])
        if spec.size_neutral:
            if "market_cap" not in frame or frame["market_cap"].notna().sum() < 3:
                warnings.append(f"{spec.name}: size exposure is not neutralized")
                statuses[spec.name] = FactorSignalStatus.NOT_VALIDATED
            else:
                neutralized = _size_residual(neutralized, frame["market_cap"])
        neutralized = _robust_zscore(neutralized)
        output[f"{spec.name}__normalized"] = neutralized
        statuses.setdefault(spec.name, FactorSignalStatus.VALID)
    normalized_columns = [f"{spec.name}__normalized" for spec in specs]
    output["factor_availability"] = output[normalized_columns].notna().sum(axis=1)
    output["factor_coverage"] = output["factor_availability"] / max(1, len(specs))
    output["confidence_penalty"] = output["factor_coverage"].clip(0, 1)
    output["eligible"] = output["factor_availability"] >= minimum_required_factors
    output.loc[~output["eligible"], normalized_columns] = np.nan
    return FactorCrossSectionResult(
        output.reset_index(drop=True), statuses, coverage, tuple(dict.fromkeys(warnings)), as_of
    )


def _robust_zscore(values: pd.Series) -> pd.Series:
    valid = values.dropna().astype(float)
    result = pd.Series(np.nan, index=values.index, dtype=float)
    if valid.empty:
        return result
    median = float(valid.median())
    mad = float((valid - median).abs().median())
    if mad > 1e-12:
        result.loc[valid.index] = 0.6744897501960817 * (valid - median) / mad
    else:
        deviation = float(valid.std(ddof=1)) if len(valid) > 1 else 0.0
        result.loc[valid.index] = (valid - median) / deviation if deviation > 1e-12 else 0.0
    return result.clip(-5.0, 5.0)


def _within_group_center(values: pd.Series, groups: pd.Series) -> pd.Series:
    result = values.copy()
    labels = groups.fillna("__UNKNOWN__").astype(str)
    for _name, indexes in labels.groupby(labels).groups.items():
        valid = values.loc[indexes].dropna()
        if len(valid) >= 3:
            result.loc[valid.index] = valid - valid.median()
    return result


def _size_residual(values: pd.Series, market_cap: pd.Series) -> pd.Series:
    size = pd.to_numeric(market_cap, errors="coerce")
    valid_mask = values.notna() & size.notna() & (size > 0)
    result = values.copy()
    if valid_mask.sum() < 3:
        return result
    x = np.log(size.loc[valid_mask].astype(float).to_numpy())
    y = values.loc[valid_mask].astype(float).to_numpy()
    design = np.column_stack([np.ones(len(x)), x])
    coefficients, *_unused = np.linalg.lstsq(design, y, rcond=None)
    residuals = y - design @ coefficients
    result.loc[valid_mask] = residuals
    return result

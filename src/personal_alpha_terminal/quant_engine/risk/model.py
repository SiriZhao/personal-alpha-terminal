from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite, sqrt

import numpy as np
import pandas as pd


class RiskModelStatus(StrEnum):
    VALID = "VALID"
    DIAGONAL_FALLBACK = "DIAGONAL_FALLBACK"
    BLOCKED = "BLOCKED"


class SizeExposureStatus(StrEnum):
    VALID = "VALID"
    NOT_VALIDATED = "NOT_VALIDATED"


@dataclass(frozen=True, slots=True)
class AssetRiskMetadata:
    symbol: str
    sector: str
    average_daily_dollar_volume: float
    size_score: float | None = None
    market_cap: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.sector.strip():
            raise ValueError("risk metadata requires symbol and sector")
        if not isfinite(self.average_daily_dollar_volume) or self.average_daily_dollar_volume <= 0:
            raise ValueError("risk metadata requires known positive ADV")
        if self.size_score is not None and not isfinite(self.size_score):
            raise ValueError("size score must be finite")
        if self.market_cap is not None and (
            not isfinite(self.market_cap) or self.market_cap <= 0
        ):
            raise ValueError("market_cap must be positive when present")


@dataclass(frozen=True, slots=True)
class RiskModelEstimate:
    symbols: tuple[str, ...]
    annualized_covariance: np.ndarray
    correlation: np.ndarray
    annualized_volatility: dict[str, float]
    beta: dict[str, float]
    sectors: dict[str, str]
    average_daily_dollar_volume: dict[str, float]
    size_scores: dict[str, float]
    size_exposure_status: SizeExposureStatus
    observations: int
    status: RiskModelStatus
    condition_number: float
    shrinkage: float
    model_version: str
    limitations: tuple[str, ...]
    market_caps: dict[str, float] = field(default_factory=dict)

    @property
    def valid_for_optimization(self) -> bool:
        return self.status in {RiskModelStatus.VALID, RiskModelStatus.DIAGONAL_FALLBACK}


@dataclass(frozen=True, slots=True)
class RiskModelConfig:
    minimum_observations: int = 60
    annualization_sessions: int = 252
    minimum_eigenvalue: float = 1e-8
    maximum_condition_number: float = 1e8
    diagonal_fallback_condition: float = 1e12
    model_version: str = "lw-risk-v1"

    def __post_init__(self) -> None:
        if self.minimum_observations < 3 or self.annualization_sessions <= 0:
            raise ValueError("risk model observation and annualization settings are invalid")
        if self.minimum_eigenvalue <= 0:
            raise ValueError("risk model eigenvalue floor must be positive")
        if not 1 < self.maximum_condition_number <= self.diagonal_fallback_condition:
            raise ValueError("risk model condition-number thresholds are inconsistent")
        if not self.model_version.strip():
            raise ValueError("risk model version is required")


class PortfolioRiskModel:
    def __init__(self, config: RiskModelConfig | None = None) -> None:
        self.config = config or RiskModelConfig()

    def fit(
        self,
        returns: pd.DataFrame,
        *,
        metadata: tuple[AssetRiskMetadata, ...],
        benchmark_returns: pd.Series,
    ) -> RiskModelEstimate:
        symbols = tuple(item.symbol for item in metadata)
        if len(symbols) != len(set(symbols)) or not symbols:
            raise ValueError("risk universe requires unique symbols")
        if returns.empty or not isinstance(returns.index, pd.DatetimeIndex):
            return self._blocked(symbols, metadata, 0, "risk return history is unavailable")
        if returns.index.has_duplicates or not returns.index.is_monotonic_increasing:
            return self._blocked(
                symbols, metadata, 0, "risk return dates are not unique and sorted"
            )
        missing = set(symbols) - set(returns.columns)
        if missing:
            raise ValueError(f"risk returns miss symbols: {sorted(missing)}")
        panel = returns.loc[:, list(symbols)].replace([np.inf, -np.inf], np.nan).dropna()
        benchmark = pd.to_numeric(benchmark_returns, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        aligned = panel.join(benchmark.rename("__benchmark__"), how="inner").dropna()
        if len(aligned) < self.config.minimum_observations:
            return self._blocked(symbols, metadata, len(aligned), "insufficient aligned returns")
        values = aligned.loc[:, list(symbols)].to_numpy(dtype=float)
        sample_variance = np.var(values, axis=0, ddof=1)
        if np.any(~np.isfinite(sample_variance)) or np.any(sample_variance <= 0):
            return self._blocked(symbols, metadata, len(aligned), "zero or invalid asset variance")

        covariance, shrinkage, limitations = self._shrink_covariance(values)
        covariance *= self.config.annualization_sessions
        covariance = _nearest_psd(covariance, self.config.minimum_eigenvalue)
        condition = float(np.linalg.cond(covariance))
        status = RiskModelStatus.VALID
        if not isfinite(condition) or condition > self.config.maximum_condition_number:
            covariance = np.diag(np.diag(covariance))
            condition = float(np.linalg.cond(covariance))
            status = RiskModelStatus.DIAGONAL_FALLBACK
            limitations = (*limitations, "ill-conditioned covariance replaced by diagonal model")
        if not np.all(np.isfinite(covariance)) or condition > self.config.maximum_condition_number:
            return self._blocked(
                symbols,
                metadata,
                len(aligned),
                "covariance remains ill-conditioned",
            )
        diagonal = np.sqrt(np.diag(covariance))
        correlation = covariance / np.outer(diagonal, diagonal)
        correlation = np.clip(correlation, -1.0, 1.0)
        benchmark_values = aligned["__benchmark__"].to_numpy(dtype=float)
        benchmark_variance = float(np.var(benchmark_values, ddof=1))
        if benchmark_variance <= 0 or not isfinite(benchmark_variance):
            return self._blocked(symbols, metadata, len(aligned), "benchmark variance is invalid")
        beta = {
            symbol: float(
                np.cov(values[:, index], benchmark_values, ddof=1)[0, 1]
                / benchmark_variance
            )
            for index, symbol in enumerate(symbols)
        }
        if any(not isfinite(value) for value in beta.values()):
            return self._blocked(symbols, metadata, len(aligned), "asset beta is invalid")
        return RiskModelEstimate(
            symbols=symbols,
            annualized_covariance=covariance,
            correlation=correlation,
            annualized_volatility={
                symbol: float(diagonal[index]) for index, symbol in enumerate(symbols)
            },
            beta=beta,
            sectors={item.symbol: item.sector for item in metadata},
            average_daily_dollar_volume={
                item.symbol: item.average_daily_dollar_volume for item in metadata
            },
            size_scores={
                item.symbol: float(item.size_score)
                for item in metadata
                if item.size_score is not None
            },
            size_exposure_status=(
                SizeExposureStatus.VALID
                if all(item.size_score is not None for item in metadata)
                else SizeExposureStatus.NOT_VALIDATED
            ),
            observations=len(aligned),
            status=status,
            condition_number=condition,
            shrinkage=shrinkage,
            model_version=self.config.model_version,
            limitations=limitations,
            market_caps={
                item.symbol: float(item.market_cap)
                for item in metadata
                if item.market_cap is not None and isfinite(item.market_cap)
            },
        )

    def _shrink_covariance(self, values: np.ndarray) -> tuple[np.ndarray, float, tuple[str, ...]]:
        try:
            from sklearn.covariance import LedoitWolf  # type: ignore[import-untyped]

            estimator = LedoitWolf(assume_centered=False).fit(values)
            return (
                np.asarray(estimator.covariance_, dtype=float),
                float(estimator.shrinkage_),
                (),
            )
        except (ImportError, ValueError, FloatingPointError):
            sample = np.cov(values, rowvar=False, ddof=1)
            shrinkage = 0.5
            covariance = (1 - shrinkage) * sample + shrinkage * np.diag(np.diag(sample))
            return (
                covariance,
                shrinkage,
                ("Ledoit-Wolf unavailable; explicit diagonal shrinkage used",),
            )

    def _blocked(
        self,
        symbols: tuple[str, ...],
        metadata: tuple[AssetRiskMetadata, ...],
        observations: int,
        reason: str,
    ) -> RiskModelEstimate:
        size = len(symbols)
        return RiskModelEstimate(
            symbols=symbols,
            annualized_covariance=np.full((size, size), np.nan),
            correlation=np.full((size, size), np.nan),
            annualized_volatility={},
            beta={},
            sectors={item.symbol: item.sector for item in metadata},
            average_daily_dollar_volume={
                item.symbol: item.average_daily_dollar_volume for item in metadata
            },
            size_scores={
                item.symbol: float(item.size_score)
                for item in metadata
                if item.size_score is not None
            },
            size_exposure_status=(
                SizeExposureStatus.VALID
                if metadata and all(item.size_score is not None for item in metadata)
                else SizeExposureStatus.NOT_VALIDATED
            ),
            observations=observations,
            status=RiskModelStatus.BLOCKED,
            condition_number=float("inf"),
            shrinkage=0.0,
            model_version=self.config.model_version,
            limitations=(reason,),
            market_caps={
                item.symbol: float(item.market_cap)
                for item in metadata
                if item.market_cap is not None and isfinite(item.market_cap)
            },
        )


def _nearest_psd(matrix: np.ndarray, floor: float) -> np.ndarray:
    symmetric = (matrix + matrix.T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    clipped = np.maximum(eigenvalues, floor)
    return np.asarray((eigenvectors * clipped) @ eigenvectors.T, dtype=float)


def portfolio_volatility(weights: np.ndarray, covariance: np.ndarray) -> float:
    variance = float(weights @ covariance @ weights)
    if not isfinite(variance) or variance < -1e-10:
        raise ValueError("portfolio variance is invalid")
    return sqrt(max(variance, 0.0))

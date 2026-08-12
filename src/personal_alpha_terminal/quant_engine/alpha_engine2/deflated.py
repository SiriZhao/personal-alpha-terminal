"""ROUND 8: deflated evidence checks.

Research that runs many experiments must not report only the best result.
These checks quantify multiple-testing, parameter instability, sample
dependence, OOS stability and subperiod stability so a champion/challenger
comparison is not inflated by selection.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import pstdev


@dataclass(frozen=True, slots=True)
class DeflatedEvidence:
    experiments_run: int
    best_sharpe: float
    deflated_sharpe: float
    parameter_instability: float  # std of Sharpe across the parameter grid
    sample_dependence: float  # min subperiod Sharpe vs full-sample Sharpe gap
    oos_stability: float  # fraction of OOS subperiods with positive excess return
    subperiod_stability: float  # fraction of subperiods with same-sign performance
    inflated: bool

    def document(self) -> dict[str, object]:
        return {
            "experiments_run": self.experiments_run,
            "best_sharpe": self.best_sharpe,
            "deflated_sharpe": self.deflated_sharpe,
            "parameter_instability": self.parameter_instability,
            "sample_dependence": self.sample_dependence,
            "oos_stability": self.oos_stability,
            "subperiod_stability": self.subperiod_stability,
            "inflated": self.inflated,
        }


def deflate_sharpe(
    best_sharpe: float,
    experiments_run: int,
    *,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado).

    Accounts for the number of trials actually run so a lucky best result is
    not treated as skill.  Returns the expected true Sharpe after multiple
    testing.
    """
    if experiments_run < 1:
        raise ValueError("experiments_run must be positive")
    if experiments_run == 1:
        return best_sharpe
    expected_max = _expected_max_sharpe(experiments_run, skew, kurtosis)
    return float(best_sharpe - expected_max)


def parameter_instability(
    grid_sharpes: Sequence[float],
) -> float:
    """Standard deviation of Sharpe across the parameter grid.

    A high value means the result depends on a specific parameter point and is
    not robust.
    """
    if len(grid_sharpes) < 2:
        return 0.0
    return float(pstdev(grid_sharpes))


def subperiod_stability(
    subperiod_sharpes: Sequence[float],
    *,
    positive_threshold: float = 0.0,
) -> float:
    """Fraction of subperiods with the same sign (above the threshold)."""
    if not subperiod_sharpes:
        return 0.0
    return float(
        sum(1 for value in subperiod_sharpes if value > positive_threshold)
        / len(subperiod_sharpes)
    )


def sample_dependence(
    subperiod_sharpes: Sequence[float],
    full_sample_sharpe: float,
) -> float:
    """Maximum absolute gap between any subperiod Sharpe and the full sample."""
    if not subperiod_sharpes:
        return 0.0
    return float(max(abs(value - full_sample_sharpe) for value in subperiod_sharpes))


def evaluate_deflated_evidence(
    *,
    experiments_run: int,
    best_sharpe: float,
    grid_sharpes: Sequence[float],
    subperiod_sharpes: Sequence[float],
    oos_subperiod_returns: Sequence[float],
    min_oos_stability: float = 0.5,
    max_parameter_instability: float = 1.0,
) -> DeflatedEvidence:
    """Combine the deflation checks into one verdict.

    A result is inflated when the best Sharpe is not explained by the number of
    trials (deflated Sharpe near zero), parameters are unstable, or OOS
    subperiods are not consistently positive.
    """
    deflated = deflate_sharpe(best_sharpe, experiments_run)
    instability = parameter_instability(grid_sharpes)
    dependence = sample_dependence(subperiod_sharpes, best_sharpe)
    oos_stability = subperiod_stability(oos_subperiod_returns)
    subperiod_stability_value = subperiod_stability(subperiod_sharpes)
    inflated = bool(
        deflated <= 0.0
        or instability > max_parameter_instability
        or oos_stability < min_oos_stability
    )
    return DeflatedEvidence(
        experiments_run=experiments_run,
        best_sharpe=best_sharpe,
        deflated_sharpe=deflated,
        parameter_instability=instability,
        sample_dependence=dependence,
        oos_stability=oos_stability,
        subperiod_stability=subperiod_stability_value,
        inflated=inflated,
    )


def _expected_max_sharpe(experiments: int, skew: float, kurtosis: float) -> float:
    """Approximate expected maximum Sharpe from N independent trials."""
    import math

    from scipy.stats import norm

    # Standard approximation for the expected maximum of N standard normals.
    # E[max] ~ (1-gamma) * Phi^{-1}(1 - 1/N) + gamma * Phi^{-1}(1 - 1/(N*e))
    euler = 0.5772156649
    q = 1.0 - 1.0 / experiments
    expected_max = (1 - euler) * norm.ppf(q) + euler * norm.ppf(q ** math.e)
    return float(expected_max)

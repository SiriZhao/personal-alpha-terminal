from __future__ import annotations

from math import sqrt
from statistics import fmean, pstdev

from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    FactorEvidence,
    FactorWeightingResult,
)

METHODS = (
    "equal_weight",
    "fixed_theory",
    "rolling_ic",
    "risk_constrained",
    "regularized",
)


def compare_factor_weighting(
    factors: tuple[FactorEvidence, ...],
    *,
    minimum_train_periods: int = 6,
    minimum_validation_periods: int = 6,
    maximum_factor_weight: float = 0.40,
    complexity_improvement_z: float = 1.0,
) -> FactorWeightingResult:
    """Fit factor weights using train/validation IC only; the locked test is absent by design."""

    if not 0 < maximum_factor_weight <= 1:
        raise ValueError("maximum_factor_weight must be in (0, 1]")
    eligible = tuple(
        item
        for item in factors
        if item.available
        and len(item.train_ic) >= minimum_train_periods
        and len(item.validation_ic) >= minimum_validation_periods
    )
    reasons = [
        f"disabled factor {item.name}: unavailable or insufficient train/validation history"
        for item in factors
        if item not in eligible
    ]
    if not eligible:
        return FactorWeightingResult(
            candidates={},
            selected_method="none",
            selected_weights={},
            validation_score=None,
            reasons=tuple(reasons or ["no eligible point-in-time factors"]),
        )
    if len(eligible) * maximum_factor_weight < 1 - 1e-12:
        reasons.append(
            "eligible factor breadth cannot satisfy the maximum-factor-weight constraint"
        )
        return FactorWeightingResult(
            candidates={},
            selected_method="none",
            selected_weights={},
            validation_score=None,
            reasons=tuple(reasons),
        )

    equal = _normalize({item.name: 1.0 for item in eligible}, maximum_factor_weight)
    theory = _normalize(
        {item.name: item.theoretical_weight for item in eligible},
        maximum_factor_weight,
    )
    robust_ic = {
        item.name: max(
            0.0,
            0.35 * fmean(item.train_ic) + 0.65 * fmean(item.validation_ic),
        )
        * (1 - item.instability_penalty)
        for item in eligible
    }
    rolling = _normalize(robust_ic, maximum_factor_weight) or equal
    risk_adjusted = {
        item.name: robust_ic[item.name] / max(pstdev(item.validation_ic), 0.02)
        for item in eligible
    }
    constrained = _normalize(risk_adjusted, maximum_factor_weight) or equal
    regularized = _normalize(
        {
            item.name: 0.5 * equal[item.name] + 0.5 * rolling[item.name]
            for item in eligible
        },
        maximum_factor_weight,
    )
    candidates = {
        "equal_weight": equal,
        "fixed_theory": theory or equal,
        "rolling_ic": rolling,
        "risk_constrained": constrained,
        "regularized": regularized,
    }

    equal_series = _weighted_ic_series(eligible, equal)
    equal_score = fmean(equal_series)
    selected_method = "equal_weight"
    selected_score = equal_score
    for method in METHODS[1:]:
        series = _weighted_ic_series(eligible, candidates[method])
        differences = tuple(value - base for value, base in zip(series, equal_series, strict=True))
        improvement = fmean(differences)
        standard_error = pstdev(differences) / sqrt(len(differences))
        if improvement > complexity_improvement_z * max(standard_error, 1e-12):
            score = fmean(series)
            if score > selected_score:
                selected_method = method
                selected_score = score

    if selected_method == "equal_weight":
        reasons.append("complex weighting did not stably improve validation IC; kept equal weight")
    else:
        reasons.append(
            f"selected {selected_method} using validation IC; locked test remains untouched"
        )
    return FactorWeightingResult(
        candidates=candidates,
        selected_method=selected_method,
        selected_weights=candidates[selected_method],
        validation_score=selected_score,
        reasons=tuple(reasons),
    )


def _weighted_ic_series(
    factors: tuple[FactorEvidence, ...],
    weights: dict[str, float],
) -> tuple[float, ...]:
    length = min(len(item.validation_ic) for item in factors)
    return tuple(
        sum(weights[item.name] * item.validation_ic[index] for item in factors)
        for index in range(length)
    )


def _normalize(raw: dict[str, float], cap: float) -> dict[str, float]:
    positive = {name: max(0.0, value) for name, value in raw.items() if value > 0}
    if not positive:
        return {}
    weights = {name: value / sum(positive.values()) for name, value in positive.items()}
    fixed: set[str] = set()
    for _ in range(len(weights) + 1):
        breaches = {name for name, value in weights.items() if value > cap + 1e-12}
        new = breaches - fixed
        if not new:
            break
        fixed |= new
        for name in fixed:
            weights[name] = cap
        flexible = [name for name in weights if name not in fixed]
        remaining = max(0.0, 1 - cap * len(fixed))
        denominator = sum(positive[name] for name in flexible)
        if not flexible or denominator <= 0:
            break
        for name in flexible:
            weights[name] = remaining * positive[name] / denominator
    if sum(weights.values()) < 1 - 1e-10:
        return {}
    return weights

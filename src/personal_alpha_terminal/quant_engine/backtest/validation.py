from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from json import dumps
from math import isfinite


@dataclass(frozen=True, slots=True)
class TimeSeriesSplit:
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if not (
            self.train_start <= self.train_end
            < self.validation_start
            <= self.validation_end
            < self.test_start
            <= self.test_end
        ):
            raise ValueError("TRAIN, VALIDATION and OUT_OF_SAMPLE windows must not overlap")


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: int
    split: TimeSeriesSplit
    embargo_sessions: int
    parameter_lock_required: bool = True


def build_walk_forward_folds(
    sessions: tuple[date, ...],
    *,
    train_sessions: int,
    validation_sessions: int,
    test_sessions: int,
    step_sessions: int,
    embargo_sessions: int = 1,
) -> tuple[WalkForwardFold, ...]:
    """Create deterministic chronological TRAIN/VALIDATION/OOS folds.

    The caller must supply a verified exchange-session calendar. No shuffle or
    calendar-day inference is performed.
    """

    if tuple(sorted(set(sessions))) != sessions:
        raise ValueError("walk-forward sessions must be sorted and unique")
    sizes = (train_sessions, validation_sessions, test_sessions, step_sessions)
    if any(value < 1 for value in sizes) or embargo_sessions < 0:
        raise ValueError("walk-forward window sizes are invalid")
    required = train_sessions + validation_sessions + test_sessions + 2 * embargo_sessions
    if len(sessions) < required:
        raise ValueError("insufficient verified sessions for one walk-forward fold")
    output: list[WalkForwardFold] = []
    start = 0
    while start + required <= len(sessions):
        train_end = start + train_sessions - 1
        validation_start = train_end + 1 + embargo_sessions
        validation_end = validation_start + validation_sessions - 1
        test_start = validation_end + 1 + embargo_sessions
        test_end = test_start + test_sessions - 1
        output.append(
            WalkForwardFold(
                len(output) + 1,
                TimeSeriesSplit(
                    sessions[start],
                    sessions[train_end],
                    sessions[validation_start],
                    sessions[validation_end],
                    sessions[test_start],
                    sessions[test_end],
                ),
                embargo_sessions,
            )
        )
        start += step_sessions
    if any(
        right.split.test_start <= left.split.test_start
        for left, right in zip(output, output[1:], strict=False)
    ):
        raise ArithmeticError("walk-forward OOS windows did not advance")
    return tuple(output)


@dataclass(frozen=True, slots=True)
class LockedParameters:
    values: dict[str, object]
    train_period: tuple[date, date]
    validation_period: tuple[date, date]
    locked_before_test: bool

    @property
    def fingerprint(self) -> str:
        return sha256(
            dumps(asdict(self), default=str, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def require_untouched(self, observed_fingerprint: str) -> None:
        if not self.locked_before_test or observed_fingerprint != self.fingerprint:
            raise RuntimeError("OOS parameters were not locked before the test period")


@dataclass(frozen=True, slots=True)
class RobustnessScenario:
    name: str
    parameter_multiplier: float = 1.0
    execution_delay_sessions: int = 0
    spread_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    rebalance_day_offset: int = 0


@dataclass(frozen=True, slots=True)
class RobustnessObservation:
    scenario: RobustnessScenario
    net_return: float
    maximum_drawdown: float
    sharpe: float | None


@dataclass(frozen=True, slots=True)
class RobustnessAssessment:
    status: str
    median_return: float
    worst_return: float
    worst_drawdown: float
    failed_scenarios: tuple[str, ...]


def assess_robustness(
    observations: tuple[RobustnessObservation, ...],
    *,
    maximum_return_degradation: float = 0.50,
    maximum_drawdown_multiplier: float = 1.75,
) -> RobustnessAssessment:
    if len(observations) < 5:
        raise ValueError("robustness assessment requires at least five scenarios")
    if any(
        not isfinite(item.net_return) or not isfinite(item.maximum_drawdown)
        for item in observations
    ):
        raise ValueError("robustness results must be finite")
    base = next((item for item in observations if item.scenario.name == "base"), None)
    if base is None:
        raise ValueError("robustness assessment requires a base scenario")
    return_floor = base.net_return - abs(base.net_return) * maximum_return_degradation
    drawdown_limit = abs(base.maximum_drawdown) * maximum_drawdown_multiplier
    failed = tuple(
        item.scenario.name
        for item in observations
        if item.net_return < return_floor
        or abs(item.maximum_drawdown) > drawdown_limit + 1e-12
    )
    ordered = sorted(item.net_return for item in observations)
    midpoint = len(ordered) // 2
    median = (
        ordered[midpoint]
        if len(ordered) % 2
        else (ordered[midpoint - 1] + ordered[midpoint]) / 2
    )
    return RobustnessAssessment(
        status="UNSTABLE" if failed else "VALIDATING",
        median_return=median,
        worst_return=min(ordered),
        worst_drawdown=min(item.maximum_drawdown for item in observations),
        failed_scenarios=failed,
    )

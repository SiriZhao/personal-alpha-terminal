from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil, isfinite, sqrt
from typing import Protocol

from personal_alpha_terminal.backtest.schemas import (
    EventSignal,
    FactorSnapshot,
    StrategyContext,
    TargetAllocation,
)


class BacktestStrategy(Protocol):
    @property
    def name(self) -> str: ...

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None: ...

    def audit_payload(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class FactorQuantileStrategy:
    """Long-only equal-weight selection from point-in-time factor snapshots."""

    factor_name: str
    factor_snapshots: tuple[FactorSnapshot, ...]
    top_quantile: float = 0.20
    minimum_assets: int = 5

    def __post_init__(self) -> None:
        if not 0 < self.top_quantile <= 1:
            raise ValueError("top_quantile must be in (0, 1]")
        if self.minimum_assets < 1:
            raise ValueError("minimum_assets must be positive")

    @property
    def name(self) -> str:
        return f"factor_quantile:{self.factor_name}"

    def audit_payload(self) -> dict[str, object]:
        return {
            "type": "factor_quantile",
            "factor_name": self.factor_name,
            "top_quantile": self.top_quantile,
            "minimum_assets": self.minimum_assets,
            "snapshots": [
                {
                    "as_of_date": item.as_of_date.isoformat(),
                    "available_at": item.available_at.isoformat(),
                    "source": item.source,
                    "values": {
                        str(asset_id): value for asset_id, value in sorted(item.values.items())
                    },
                }
                for item in sorted(
                    self.factor_snapshots,
                    key=lambda value: (
                        value.as_of_date,
                        value.available_at,
                        value.source,
                    ),
                )
            ],
        }

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        eligible = [
            item
            for item in self.factor_snapshots
            if item.as_of_date <= context.signal_date and item.available_at <= context.signal_cutoff
        ]
        if not eligible:
            return None
        snapshot = max(
            eligible,
            key=lambda item: (item.as_of_date, item.available_at, item.source),
        )
        values = {
            asset_id: float(value)
            for asset_id, value in snapshot.values.items()
            if asset_id in context.history and isfinite(float(value))
        }
        if len(values) < self.minimum_assets:
            return None
        count = max(1, ceil(len(values) * self.top_quantile))
        selected = sorted(values, key=lambda item: (-values[item], item))[:count]
        weight = 1.0 / len(selected)
        return TargetAllocation(
            weights={item: weight for item in selected},
            rationale=(
                f"factor={self.factor_name}",
                f"factor_as_of={snapshot.as_of_date.isoformat()}",
                f"factor_available_at={snapshot.available_at.isoformat()}",
                f"factor_source={snapshot.source}",
                f"selected_top_quantile={self.top_quantile:.2%}",
                "equal_weight_long_only",
            ),
        )


@dataclass(frozen=True, slots=True)
class EventFollowStrategy:
    """Allocate after an event is known; execution remains next-session open."""

    events: tuple[EventSignal, ...]
    target_weight: float = 1.0
    holding_sessions: int = 5

    def __post_init__(self) -> None:
        if not 0 < self.target_weight <= 1:
            raise ValueError("target_weight must be in (0, 1]")
        if self.holding_sessions < 1:
            raise ValueError("holding_sessions must be positive")

    @property
    def name(self) -> str:
        return "event_follow"

    def audit_payload(self) -> dict[str, object]:
        return {
            "type": "event_follow",
            "target_weight": self.target_weight,
            "holding_sessions": self.holding_sessions,
            "events": [
                {
                    "event_date": item.event_date.isoformat(),
                    "available_at": item.available_at.isoformat(),
                    "source_asset_id": item.source_asset_id,
                    "target_asset_id": item.target_asset_id,
                    "event_type": item.event_type,
                    "description": item.description,
                }
                for item in sorted(
                    self.events,
                    key=lambda value: (
                        value.event_date,
                        value.available_at,
                        value.source_asset_id,
                        value.target_asset_id,
                    ),
                )
            ],
        }

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        session_index = {item: index for index, item in enumerate(context.calendar)}
        current_index = session_index[context.signal_date]
        active: list[EventSignal] = []
        for event in self.events:
            available_index = next(
                (
                    session_index[session]
                    for session in context.calendar
                    if session >= event.event_date
                    and context.decision_cutoffs[session] >= event.available_at
                ),
                None,
            )
            if (
                available_index is not None
                and 0 <= current_index - available_index < self.holding_sessions
                and event.available_at <= context.signal_cutoff
                and event.target_asset_id in context.history
            ):
                active.append(event)
        if not active:
            if context.current_weights:
                return TargetAllocation(
                    weights={},
                    rationale=("event_holding_window_expired", "move_to_cash"),
                )
            return None
        target_ids = sorted({item.target_asset_id for item in active})
        weight = self.target_weight / len(target_ids)
        return TargetAllocation(
            weights={item: weight for item in target_ids},
            rationale=tuple(
                [
                    "event_data_filtered_by_available_at",
                    f"holding_sessions={self.holding_sessions}",
                    *[
                        f"{item.event_type}:{item.source_asset_id}->{item.target_asset_id}"
                        for item in active
                    ],
                ]
            ),
        )


@dataclass(frozen=True, slots=True)
class RotationStrategy:
    """Select the strongest groups from trailing adjusted-close returns."""

    group_by_asset: Mapping[int, str]
    lookback_sessions: int = 63
    top_groups: int = 1

    def __post_init__(self) -> None:
        if self.lookback_sessions < 2:
            raise ValueError("lookback_sessions must be at least 2")
        if self.top_groups < 1:
            raise ValueError("top_groups must be positive")

    @property
    def name(self) -> str:
        return "group_rotation"

    def audit_payload(self) -> dict[str, object]:
        return {
            "type": "group_rotation",
            "group_by_asset": {
                str(asset_id): group for asset_id, group in sorted(self.group_by_asset.items())
            },
            "lookback_sessions": self.lookback_sessions,
            "top_groups": self.top_groups,
        }

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        group_returns: dict[str, list[float]] = {}
        eligible_assets: list[int] = []
        for asset_id, history in context.history.items():
            group = self.group_by_asset.get(asset_id)
            if group is None or len(history) <= self.lookback_sessions:
                continue
            start = history[-self.lookback_sessions - 1].adjusted_close
            end = history[-1].adjusted_close
            if start is None or end is None or start <= 0:
                continue
            group_returns.setdefault(group, []).append(end / start - 1)
            eligible_assets.append(asset_id)
        if not group_returns:
            return None
        scores = {group: sum(values) / len(values) for group, values in group_returns.items()}
        selected_groups = sorted(scores, key=lambda item: (-scores[item], item))[: self.top_groups]
        selected_assets = sorted(
            item for item in eligible_assets if self.group_by_asset[item] in selected_groups
        )
        if not selected_assets:
            return None
        weight = 1.0 / len(selected_assets)
        return TargetAllocation(
            weights={item: weight for item in selected_assets},
            rationale=(
                f"trailing_sessions={self.lookback_sessions}",
                f"selected_groups={','.join(selected_groups)}",
                "group_score=equal_weight_mean_member_return",
            ),
        )


@dataclass(frozen=True, slots=True)
class ETFAllocationStrategy:
    """Interpretable momentum screen with inverse-volatility allocation."""

    asset_ids: tuple[int, ...]
    momentum_sessions: int = 63
    volatility_sessions: int = 21
    top_k: int = 2

    def __post_init__(self) -> None:
        if self.momentum_sessions < 2 or self.volatility_sessions < 2:
            raise ValueError("momentum and volatility windows must be at least 2")
        if self.top_k < 1:
            raise ValueError("top_k must be positive")

    @property
    def name(self) -> str:
        return "etf_dynamic_allocation"

    def audit_payload(self) -> dict[str, object]:
        return {
            "type": "etf_dynamic_allocation",
            "asset_ids": list(self.asset_ids),
            "momentum_sessions": self.momentum_sessions,
            "volatility_sessions": self.volatility_sessions,
            "top_k": self.top_k,
        }

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        scored: list[tuple[int, float, float]] = []
        required = max(self.momentum_sessions, self.volatility_sessions)
        for asset_id in self.asset_ids:
            history = context.history.get(asset_id, ())
            if len(history) <= required:
                continue
            closes = [item.adjusted_close for item in history]
            if any(item is None or item <= 0 for item in closes[-required - 1 :]):
                continue
            numeric = [float(item) for item in closes if item is not None]
            momentum = numeric[-1] / numeric[-self.momentum_sessions - 1] - 1
            recent = numeric[-self.volatility_sessions - 1 :]
            returns = [recent[index] / recent[index - 1] - 1 for index in range(1, len(recent))]
            mean = sum(returns) / len(returns)
            variance = sum((item - mean) ** 2 for item in returns) / max(
                len(returns) - 1,
                1,
            )
            volatility = sqrt(variance)
            if isfinite(volatility) and isfinite(momentum):
                scored.append((asset_id, momentum, max(volatility, 1e-8)))
        if not scored:
            return None
        selected = sorted(scored, key=lambda item: (-item[1], item[0]))[: self.top_k]
        inverse_volatility = {item[0]: 1 / item[2] for item in selected}
        denominator = sum(inverse_volatility.values())
        return TargetAllocation(
            weights={
                asset_id: value / denominator for asset_id, value in inverse_volatility.items()
            },
            rationale=(
                f"momentum_sessions={self.momentum_sessions}",
                f"volatility_sessions={self.volatility_sessions}",
                f"top_k={self.top_k}",
                "inverse_volatility_weighting",
            ),
        )
